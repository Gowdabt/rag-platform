const { app, BrowserWindow, Menu, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

const HOST = "127.0.0.1";
const PORT = Number(process.env.RAG_DESKTOP_PORT || 17800);
const OAUTH_HOSTS = new Set([
  "accounts.google.com",
  "login.microsoftonline.com",
  "login.live.com",
  "www.dropbox.com",
  "dropbox.com",
]);

let mainWindow = null;
let apiProcess = null;
let stopping = false;

function repoRoot() {
  if (app.isPackaged) return process.resourcesPath;
  return path.resolve(__dirname, "..");
}

function parseEnvFile(file) {
  if (!fs.existsSync(file)) return {};
  const out = {};
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const text = line.trim();
    if (!text || text.startsWith("#")) continue;
    const index = text.indexOf("=");
    if (index < 1) continue;
    let value = text.slice(index + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[text.slice(0, index).trim()] = value;
  }
  return out;
}

function pythonBin(root) {
  const unix = path.join(root, "backend", ".venv", "bin", "python");
  const win = path.join(root, "backend", ".venv", "Scripts", "python.exe");
  if (fs.existsSync(unix)) return unix;
  if (fs.existsSync(win)) return win;
  return process.platform === "win32" ? "python" : "python3";
}

function waitForHealth(timeoutMs = 40000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get({ host: HOST, port: PORT, path: "/api/v1/health", timeout: 1500 }, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) {
          resolve();
          return;
        }
        retry();
      });
      req.on("error", retry);
      req.on("timeout", () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error("The local engine did not become ready. Check Postgres and the API log."));
        return;
      }
      setTimeout(tick, 400);
    };
    tick();
  });
}

function startApi(root) {
  const backendDir = path.join(root, "backend");
  const frontendDist = path.join(root, "frontend", "dist");
  const configDir = path.join(root, "configs");
  const envFile = path.join(root, ".env");
  const userEnv = path.join(app.getPath("userData"), ".env");
  const env = {
    ...process.env,
    ...parseEnvFile(envFile),
    ...parseEnvFile(userEnv),
    RAG_ENV: process.env.RAG_ENV || "development",
    RAG_CONFIG_DIR: configDir,
    RAG_SERVE_FRONTEND: "1",
    RAG_FRONTEND_DIST: frontendDist,
    PYTHONPATH: backendDir,
  };
  const python = pythonBin(root);
  const args = ["-m", "uvicorn", "app.main:app", "--host", HOST, "--port", String(PORT), "--log-level", "info"];
  apiProcess = spawn(python, args, {
    cwd: backendDir,
    env,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  const logPath = path.join(app.getPath("userData"), "engine.log");
  const log = fs.createWriteStream(logPath, { flags: "a" });
  apiProcess.stdout.pipe(log);
  apiProcess.stderr.pipe(log);
  apiProcess.on("exit", (code) => {
    if (!stopping && mainWindow && !mainWindow.isDestroyed()) {
      showError(`Local engine exited (code ${code}). See ${logPath}`);
    }
  });
  return apiProcess;
}

function showError(message) {
  const html = `<!doctype html><html><body style="font-family:Inter,system-ui,sans-serif;background:#f8f9ff;color:#0b1c30;padding:48px;margin:0;-webkit-app-region:drag">
    <h1 style="font-size:20px">RAG Platform could not start</h1>
    <p style="color:#5b6475;max-width:520px">${String(message).replace(/[<>&]/g, "")}</p>
    <p style="color:#5b6475">Postgres must be running, then launch the app again.</p>
  </body></html>`;
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
}

function isLocalUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost";
  } catch {
    return false;
  }
}

function isOauthHost(url) {
  try {
    const host = new URL(url).hostname;
    if (OAUTH_HOSTS.has(host)) return true;
    return [...OAUTH_HOSTS].some((allowed) => host.endsWith(`.${allowed}`));
  } catch {
    return false;
  }
}

function createWindow() {
  const isMac = process.platform === "darwin";
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#f8f9ff",
    title: "RAG Platform",
    icon: path.join(__dirname, "icon.png"),
    show: false,
    autoHideMenuBar: true,
    titleBarStyle: isMac ? "hiddenInset" : "hidden",
    trafficLightPosition: { x: 16, y: 18 },
    titleBarOverlay: isMac
      ? undefined
      : { color: "#ffffff", symbolColor: "#0b1c30", height: 40 },
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isLocalUrl(url) || isOauthHost(url)) return { action: "allow" };
    shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (isLocalUrl(url) || isOauthHost(url)) return;
    event.preventDefault();
    shell.openExternal(url);
  });
  return mainWindow;
}

function installMenu() {
  if (process.platform === "darwin") {
    Menu.setApplicationMenu(
      Menu.buildFromTemplate([{ role: "appMenu" }, { role: "editMenu" }, { role: "viewMenu" }, { role: "windowMenu" }]),
    );
    return;
  }
  Menu.setApplicationMenu(Menu.buildFromTemplate([{ role: "editMenu" }, { role: "viewMenu" }]));
}

async function boot() {
  const root = repoRoot();
  app.setName("RAG Platform");
  installMenu();
  createWindow();
  await mainWindow.loadFile(path.join(__dirname, "splash.html"));
  const dist = path.join(root, "frontend", "dist", "index.html");
  if (!fs.existsSync(dist)) {
    showError("The UI has not been built. From the repo run: cd frontend && npm run build");
    return;
  }
  startApi(root);
  try {
    await waitForHealth();
    await mainWindow.loadURL(`http://${HOST}:${PORT}/`);
  } catch (error) {
    showError(error.message || String(error));
  }
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  app.whenReady().then(boot);
}

app.on("before-quit", () => {
  stopping = true;
  if (!apiProcess || apiProcess.killed) return;
  if (process.platform === "win32" && apiProcess.pid) {
    spawn("taskkill", ["/pid", String(apiProcess.pid), "/f", "/t"], { windowsHide: true });
    return;
  }
  apiProcess.kill("SIGTERM");
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) boot();
});
