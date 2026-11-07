import { app, Menu, MenuItemConstructorOptions, shell } from "electron";

export const TUTORIAL_URL = "https://github.com/Juhuaaaa/shutong-releases#readme";

/** The edit menu is not decoration: on macOS, copy and paste in text fields only work through it. */
export function buildMenu({ logsDir }: { logsDir: string }): Menu {
  const template: MenuItemConstructorOptions[] = [
    ...(process.platform === "darwin" ? [{ role: "appMenu" as const }] : []),
    { role: "fileMenu" },
    { role: "editMenu" },
    { role: "windowMenu" },
    {
      label: "帮助",
      role: "help",
      submenu: [
        { label: "安装教程", click: () => void shell.openExternal(TUTORIAL_URL) },
        { label: "打开日志目录", click: () => void shell.openPath(logsDir) },
        { type: "separator" },
        { label: `书童 ${app.getVersion()}`, enabled: false },
      ],
    },
  ];
  return Menu.buildFromTemplate(template);
}
