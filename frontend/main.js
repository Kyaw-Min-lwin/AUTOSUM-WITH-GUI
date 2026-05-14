const { app, BrowserWindow } = require('electron');
const path = require('path');

function createWindow () {
  // This is where you configure your actual desktop window
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    title: "AutoSim Command Center",
    backgroundColor: '#0f172a', // Sleek dark slate background
    webPreferences: {
      nodeIntegration: false,
      webSecurity: false,
      contextIsolation: true,
      sandbox: false
    }
  });

  // Load our single-file UI
  win.loadFile(path.join(__dirname, 'index.html'));

  // Optional: Open the DevTools automatically so you can see console.logs!
  win.webContents.openDevTools();
}

// When Electron is ready, spawn the window
app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// Quit when all windows are closed (except on macOS)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});