//! Ziko desktop shell (Phase 2): dot + panel windows, tray, global shortcut, single instance,
//! and ownership of the Python backend process.

mod backend;

use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent};

use backend::Backend;

/// Ask the dot window to toggle the panel. Positioning logic lives in one place (TS, services/windows.ts).
fn toggle_panel(app: &AppHandle) {
    if let Some(dot) = app.get_webview_window("dot") {
        let _ = dot.show();
    }
    let _ = app.emit_to("dot", "ziko://toggle-panel", ());
}

fn quit(app: &AppHandle) {
    app.state::<Backend>().kill();
    app.exit(0);
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    quit(&app);
}

#[derive(serde::Serialize)]
struct GlassSupport {
    os: &'static str,
    /// false only on Linux/X11 without a compositor — the UI must then fall back to an opaque panel.
    compositor: bool,
    session: Option<String>,
}

/// What the desktop can do for see-through glass. Sync command → runs on the main thread (GTK requirement).
#[tauri::command]
fn glass_support(window: tauri::WebviewWindow) -> GlassSupport {
    #[cfg(target_os = "linux")]
    let compositor = {
        use gtk::prelude::WidgetExt;
        window
            .gtk_window()
            .ok()
            .and_then(|w| w.screen())
            .map(|s| s.is_composited())
            .unwrap_or(false)
    };
    #[cfg(not(target_os = "linux"))]
    let compositor = {
        let _ = &window;
        true
    };
    GlassSupport {
        os: std::env::consts::OS,
        compositor,
        session: std::env::var("XDG_SESSION_TYPE").ok(),
    }
}

/// Linux/Wayland fixes, applied before GTK starts:
///  - Wayland ignores always-on-top and app-driven window moves, so run the windows through XWayland
///    (GNOME honours both there).
///  - WebKitGTK's DMABUF renderer draws transparent windows with stray lines/ghosting on NVIDIA.
/// GDK_BACKEND is forced (VS Code's terminal exports GDK_BACKEND=wayland to every child); set
/// ZIKO_NATIVE_WAYLAND=1 to opt out. The renderer switch respects an existing value.
#[cfg(target_os = "linux")]
fn linux_env() {
    // SAFETY: called first thing in run(), before any other thread exists.
    let set = |key: &str, value: &str| unsafe { std::env::set_var(key, value) };
    if std::env::var_os("WAYLAND_DISPLAY").is_some() && std::env::var_os("ZIKO_NATIVE_WAYLAND").is_none() {
        set("GDK_BACKEND", "x11");
    }
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        set("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
}

/// On GNOME Wayland an X11 key grab only fires while one of our own windows has focus, so register
/// Ctrl+Shift+Z as a GNOME custom shortcut that relaunches Ziko; single-instance turns that into a
/// panel toggle. Idempotent: refreshes the command (exe path) on every start.
#[cfg(target_os = "linux")]
fn ensure_gnome_shortcut() {
    use std::process::Command;
    const LIST_SCHEMA: &str = "org.gnome.settings-daemon.plugins.media-keys";
    const PATH: &str = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/ziko/";

    let gnome = std::env::var("XDG_CURRENT_DESKTOP").is_ok_and(|d| d.to_uppercase().contains("GNOME"));
    if std::env::var_os("WAYLAND_DISPLAY").is_none() || !gnome {
        return;
    }
    let Ok(exe) = std::env::current_exe() else { return };
    let gsettings = |args: &[&str]| -> Option<String> {
        let out = Command::new("gsettings").args(args).output().ok()?;
        out.status.success().then(|| String::from_utf8_lossy(&out.stdout).trim().to_string())
    };

    let Some(current) = gsettings(&["get", LIST_SCHEMA, "custom-keybindings"]) else { return };
    let mut paths: Vec<String> = current
        .trim_start_matches("@as")
        .trim()
        .trim_matches(|c| c == '[' || c == ']')
        .split(',')
        .map(|p| p.trim().trim_matches('\'').to_string())
        .filter(|p| !p.is_empty())
        .collect();
    if !paths.iter().any(|p| p == PATH) {
        paths.push(PATH.to_string());
        let list = format!("[{}]", paths.iter().map(|p| format!("'{p}'")).collect::<Vec<_>>().join(", "));
        gsettings(&["set", LIST_SCHEMA, "custom-keybindings", &list]);
    }
    let schema = format!("{LIST_SCHEMA}.custom-keybinding:{PATH}");
    // GNOME parses the command shell-style; the exe path may contain spaces.
    let command = format!("'{}'", exe.display().to_string().replace('\'', r"'\''"));
    gsettings(&["set", &schema, "name", "Ziko: open panel"]);
    gsettings(&["set", &schema, "command", &command]);
    gsettings(&["set", &schema, "binding", "<Control><Shift>z"]);
}

/// Under X11 the GTK theme paints its own window background and a rounded, outlined frame behind the
/// webview — a dark square with light corners around the dot. Our windows draw everything themselves.
#[cfg(target_os = "linux")]
fn clear_gtk_chrome() {
    use gtk::prelude::CssProviderExt;
    let css = gtk::CssProvider::new();
    let rules = b"window, window.background, decoration, decoration-overlay {
        background: transparent; border: none; border-radius: 0; box-shadow: none; outline: none; margin: 0; }";
    if css.load_from_data(rules).is_err() {
        return;
    }
    if let Some(screen) = gtk::gdk::Screen::default() {
        gtk::StyleContext::add_provider_for_screen(&screen, &css, gtk::STYLE_PROVIDER_PRIORITY_USER);
    }
}

/// Window-styling GNOME extensions (rounded-window-corners, blur-my-shell…) frame every NORMAL window,
/// which draws a rounded box around the dot. They skip utility windows. Must run before the first map.
#[cfg(target_os = "linux")]
fn mark_utility(win: &tauri::WebviewWindow) {
    use gtk::prelude::GtkWindowExt;
    if let Ok(w) = win.gtk_window() {
        w.set_type_hint(gtk::gdk::WindowTypeHint::Utility);
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(target_os = "linux")]
    {
        linux_env();
        std::thread::spawn(ensure_gnome_shortcut);
    }
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| toggle_panel(app)))
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--minimized"]),
        ))
        .manage(Backend::new())
        .invoke_handler(tauri::generate_handler![backend::backend_info, quit_app, glass_support])
        .setup(|app| {
            #[cfg(target_os = "linux")]
            {
                clear_gtk_chrome();
                for label in ["dot", "panel"] {
                    if let Some(w) = app.get_webview_window(label) {
                        mark_utility(&w);
                    }
                }
            }
            // The dot starts hidden (tauri.conf.json) so its window type is set before it first appears.
            if let Some(dot) = app.get_webview_window("dot") {
                let _ = dot.show();
            }
            backend::spawn(app.handle());

            // ---- tray (PRD §3.1 / §14: "system tray control")
            let open = MenuItem::with_id(app, "open", "Open Ziko", true, None::<&str>)?;
            let mute = CheckMenuItem::with_id(app, "mute", "Mute microphone", true, false, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit Ziko", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &mute, &sep, &quit_item])?;
            let mute_for_events = mute.clone();
            TrayIconBuilder::with_id("ziko-tray")
                .icon(app.default_window_icon().cloned().expect("bundle icon missing"))
                .tooltip("Ziko")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "open" => toggle_panel(app),
                    "mute" => {
                        let muted = mute_for_events.is_checked().unwrap_or(false);
                        let _ = app.emit("ziko://mute", muted);
                    }
                    "quit" => quit(app),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        toggle_panel(tray.app_handle());
                    }
                })
                .build(app)?;

            // ---- global shortcut Ctrl+Shift+Z (PRD §3.1 "keyboard shortcut to open the panel")
            #[cfg(desktop)]
            {
                use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
                let open_sc = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyZ);
                app.handle().plugin(
                    tauri_plugin_global_shortcut::Builder::new()
                        .with_handler(move |app, sc, ev| {
                            if sc == &open_sc && ev.state() == ShortcutState::Pressed {
                                toggle_panel(app);
                            }
                        })
                        .build(),
                )?;
                if let Err(e) = app.global_shortcut().register(open_sc) {
                    // Another app owns the combo: keep running, the dot and tray still work.
                    log::warn!("could not register Ctrl+Shift+Z: {e}");
                }
            }

            // Started by autostart with --minimized: keep the dot, never pop the panel.
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Ziko");

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            app.state::<Backend>().kill(); // PRD §8.5: no orphaned backend after exit
        }
    });
}
