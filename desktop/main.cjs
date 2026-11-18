const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const page = path.join(__dirname, "ui", "index.html");
const bridge = app.isPackaged
  ? path.join(process.resourcesPath, "backend", "bridge.py")
  : path.join(__dirname, "bridge.py");
const jobs = new Set();
const running = new Set();
let directory;
let python;
let win;

if (process.platform !== "win32") {
  process.env.PATH = [
    ...new Set(
      [
        ...(process.env.PATH || "").split(path.delimiter),
        path.join(os.homedir(), ".local", "bin"),
        path.join(os.homedir(), ".volta", "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
      ].filter(Boolean),
    ),
  ].join(path.delimiter);
}
function interpreter() {
  if (python) return python;
  const names = process.env.REPO_BUGBOT_PYTHON
    ? [process.env.REPO_BUGBOT_PYTHON]
    : [
        "python3",
        "python3.14",
        "python3.13",
        "python3.12",
        "python3.11",
        "python3.10",
        "python",
      ];
  const options = names.map((name) => [name]);
  if (process.platform === "win32" && !process.env.REPO_BUGBOT_PYTHON)
    options.unshift(["py", "-3"]);
  for (const candidate of options) {
    const [exe, ...prefix] = candidate;
    const probe = spawnSync(
      exe,
      [...prefix, "-I", "-c", "import sys;sys.exit(sys.version_info < (3,10))"],
      { timeout: 3000, windowsHide: true, stdio: "ignore" },
    );
    if (probe.status === 0) return (python = candidate);
  }
  throw Error(
    "Python 3.10 or newer is required. Install Python or set REPO_BUGBOT_PYTHON.",
  );
}
function stop(proc) {
  if (!proc.pid) return;
  try {
    if (process.platform === "win32") proc.kill();
    else process.kill(-proc.pid, "SIGTERM");
  } catch {
    /* The process has already exited. */
  }
}
async function request(command, args = {}) {
  const [exe, ...prefix] = interpreter();
  return new Promise((resolve, reject) => {
    const proc = spawn(exe, [...prefix, "-I", "-B", bridge, command], {
      cwd: path.dirname(bridge),
      detached: process.platform !== "win32",
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    jobs.add(proc);
    const chunks = [];
    let size = 0;
    const timeout = setTimeout(
      () => {
        stop(proc);
        reject(Error("This operation timed out."));
      },
      command === "run" ? 15 * 60_000 : 150_000,
    );
    proc.stdout.on("data", (chunk) => {
      size += chunk.length;
      if (size > 24 * 1024 * 1024) {
        stop(proc);
        reject(Error("The result exceeds the desktop display limit."));
      } else chunks.push(chunk);
    });
    proc.stderr.resume();
    proc.stdin.on("error", () => {});
    proc.on("error", reject);
    proc.on("close", () => {
      clearTimeout(timeout);
      jobs.delete(proc);
      try {
        const result = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        if ("error" in result) reject(Error(result.error));
        else resolve(result.value);
      } catch {
        reject(Error("The Python backend exited before returning a result."));
      }
    });
    proc.stdin.end(JSON.stringify(args));
  });
}
const prefs = () => path.join(app.getPath("userData"), "workspace.json");
function remember(repo) {
  try {
    fs.writeFileSync(prefs(), JSON.stringify({ directory: repo }), {
      mode: 0o600,
    });
  } catch {}
}
function last() {
  try {
    return JSON.parse(fs.readFileSync(prefs(), "utf8")).directory;
  } catch {
    return null;
  }
}
function initialRepo() {
  const flag = process.argv.indexOf("--repo");
  if (flag !== -1 && process.argv[flag + 1])
    return path.resolve(process.argv[flag + 1]);
  return last();
}
function register(name, action) {
  ipcMain.handle("bugbot:" + name, (event, args = {}) => {
    if (
      event.sender !== win?.webContents ||
      event.senderFrame?.url !== pathToFileURL(page).href
    ) {
      throw Error("Unknown window.");
    }
    return action(args);
  });
}
app.whenReady().then(() => {
  directory = initialRepo();
  register("initial", () =>
    directory ? { name: path.basename(directory) } : null,
  );
  register("open", async () => {
    const choice = await dialog.showOpenDialog(win, {
      title: "Open a Git repository",
      properties: ["openDirectory"],
    });
    if (choice.canceled) return null;
    const next = choice.filePaths[0];
    const result = await request("history", { directory: next });
    directory = next;
    remember(next);
    return result;
  });
  for (const name of ["settings", "saveSettings", "issue"])
    register(name, (args) => request(name, args));
  for (const name of ["history", "inspect", "diff", "run"])
    register(name, async (args) => {
      if (!directory) throw Error("Open a Git repository first.");
      const selected = directory;
      const key = selected + "\0" + args.head;
      if (name !== "run")
        return request(name, { ...args, directory: selected });
      if (running.has(key))
        throw Error("A review is already running for this commit.");
      running.add(key);
      try {
        return await request(name, { ...args, directory: selected });
      } finally {
        running.delete(key);
      }
    });
  register("openIssue", (args) => {
    if (
      !/^[\w.-]+\/[\w.-]+$/.test(args.repo) ||
      !Number.isSafeInteger(args.number) ||
      args.number < 1
    )
      throw Error("Invalid GitHub reference.");
    return shell.openExternal(
      "https://github.com/" + args.repo + "/issues/" + args.number,
    );
  });
  function create() {
    win = new BrowserWindow({
      width: 1440,
      height: 900,
      minWidth: 900,
      minHeight: 620,
      icon: path.join(__dirname, "assets", "icon.png"),
      backgroundColor: "#101114",
      title: "Repo Bugbot",
      autoHideMenuBar: true,
      webPreferences: {
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        preload: path.join(__dirname, "preload.cjs"),
      },
    });
    win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    win.webContents.on("will-navigate", (event) => event.preventDefault());
    win.webContents.session.setPermissionRequestHandler(
      (_web, _permission, callback) => callback(false),
    );
    win.loadFile(page);
  }
  create();
  app.on("activate", () => {
    if (!BrowserWindow.getAllWindows().length) create();
  });
});
app.on("before-quit", () => {
  for (const job of jobs) stop(job);
});
app.on("window-all-closed", () => app.quit());
