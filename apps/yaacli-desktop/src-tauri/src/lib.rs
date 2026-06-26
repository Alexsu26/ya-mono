mod credentials;
mod sidecar;

use tauri::{menu::Menu, Manager, WindowEvent};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default();
    // A second launch focuses the existing window instead of spawning a second
    // sidecar that would race on the same workspace.
    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }));
    }
    let app = builder
        .manage(sidecar::SidecarManager::default())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            app.set_menu(Menu::default(app.handle())?)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let manager = window.state::<sidecar::SidecarManager>();
                if manager.has_active_run() {
                    api.prevent_close();
                    let _ = window.hide();
                } else {
                    window.app_handle().exit(0);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            credentials::credential_status,
            credentials::credential_set,
            credentials::credential_delete,
            sidecar::runtime_start,
            sidecar::runtime_request,
            sidecar::runtime_stop,
            sidecar::runtime_state,
        ])
        .build(tauri::generate_context!())
        .expect("error while building YAACLI Desktop");

    // Ensure the sidecar is shut down on Cmd+Q / system shutdown, not only on
    // window close — otherwise the Python process can outlive the app. The first
    // ExitRequested performs a graceful stop and then re-issues the exit; the
    // guarded second pass lets the app terminate.
    app.run(|app_handle, event| {
        if let tauri::RunEvent::ExitRequested { api, .. } = event {
            let manager = app_handle.state::<sidecar::SidecarManager>();
            if manager.begin_shutdown() {
                api.prevent_exit();
                let app_handle = app_handle.clone();
                let manager = manager.inner().clone();
                tauri::async_runtime::spawn(async move {
                    let _ = manager.stop().await;
                    app_handle.exit(0);
                });
            }
        }
    });
}

#[cfg(test)]
mod tests {
    #[test]
    fn capabilities_do_not_grant_webview_shell_access() {
        let capabilities = include_str!("../capabilities/default.json");

        assert!(!capabilities.contains("shell:"));
        assert!(!capabilities.contains("fs:"));
        assert!(capabilities.contains("dialog:allow-open"));
    }
}
