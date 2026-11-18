import { packager } from "@electron/packager";
import { cp, mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.dirname(fileURLToPath(import.meta.url));
const stage = await mkdtemp(path.join(tmpdir(), "repo-bugbot-package-"));
const backend = path.join(stage, "backend");
try {
  await mkdir(backend);
  await cp(path.join(root, "bridge.py"), path.join(backend, "bridge.py"));
  await cp(
    path.join(root, "..", "repo_bugbot"),
    path.join(backend, "repo_bugbot"),
    {
      recursive: true,
      filter: (source) =>
        !source.includes("__pycache__") && !source.endsWith(".pyc"),
    },
  );
  const apps = await packager({
    dir: root,
    name: "Repo Bugbot",
    appBundleId: "dev.repobugbot.desktop",
    out: path.join(root, "out"),
    overwrite: true,
    asar: true,
    icon: path.join(
      root,
      "assets",
      process.platform === "darwin"
        ? "icon.icns"
        : process.platform === "win32"
          ? "icon.ico"
          : "icon.png",
    ),
    osxSign:
      process.platform === "darwin"
        ? {
            identity: "-",
            identityValidation: false,
            preAutoEntitlements: false,
            // Ad-hoc signatures have no team ID for macOS hardened library validation.
            optionsForFile: () => ({
              timestamp: "none",
              hardenedRuntime: false,
              entitlements: path.join(root, "entitlements.mac.plist"),
            }),
          }
        : undefined,
    extraResource: [backend],
    ignore: [
      /^\/out(?:\/|$)/,
      /^\/test(?:\/|$)/,
      /^\/test-results(?:\/|$)/,
      /^\/bridge\.py$/,
      /^\/package\.mjs$/,
    ],
  });
  console.log(apps.join("\n"));
} finally {
  await rm(stage, { recursive: true, force: true });
}
