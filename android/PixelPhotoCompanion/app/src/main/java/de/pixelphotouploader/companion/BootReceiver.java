package de.pixelphotouploader.companion;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction()) &&
                AppState.prefs(context).getBoolean("enabled", false) &&
                AppState.prefs(context).getBoolean("safetyAccepted", false)) {
            BackupMonitorService.start(context);
        }
    }
}
