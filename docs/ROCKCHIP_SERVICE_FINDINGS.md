# Rockchip Service Findings

Observed on the rooted Scout on 2026-04-27.

## Summary

`rockchip.service` is a vendor or base-image platform setup service, not an Auto-Scout service. It is currently failed, but it should not be restarted, disabled, or edited without a separate decision because it touches low-level graphics, Android Debug Bridge startup, and power-management setup.

## Files

- Unit: `/lib/systemd/system/rockchip.service`
- Script: `/etc/init.d/rockchip.sh`
- Description: `Setup rockchip platform environment`
- Unit command: `ExecStart=/etc/init.d/rockchip.sh`

Neither file is owned by a Debian package according to `dpkg -S`, which means the files were probably placed directly by the device image or board support package instead of installed through apt.

## Likely Origin

The exact author is not identified in the files. Based on the service name, script content, and hardware detection logic, the most likely source is the Rockchip board support package or a Moorebot/OEM image build based on that BSP.

The Scout reports these device-tree compatible strings:

```text
rockchip,px30-evb-ddr3-v10-linux
rockchip,px30
```

## What The Script Does

The script detects the Rockchip chip family from `/proc/device-tree/compatible`. On this Scout, that selects `px30`.

If `/usr/local/first_boot_flag` is missing, the script enters a first-boot setup path:

- remounts `/` with synchronous writes
- installs Mali GPU userspace packages from `/packages/libmali`
- creates EGL/GLES symlinks pointing to `libMali.so`
- sets `CAP_SYS_ADMIN` on `/usr/bin/gst-launch-1.0`
- removes `/packages`
- restarts `lightdm.service` if present
- creates `/usr/local/first_boot_flag`

Outside the first-boot block, it also tries to:

- enable/start `/etc/init.d/adbd.sh`
- move power-button and triggerhappy files from `/etc/Powermanager`
- restart `triggerhappy`

## Current Failure Clues

- `rockchip.service` is enabled but failed.
- `/usr/local/first_boot_flag` is missing, so the script thinks first-boot setup has not completed.
- `/packages/libmali` exists but is empty.
- `/usr/lib/aarch64-linux-gnu/libMali.so`, `libEGL.so`, and `libGLESv2.so` were not found during inspection.
- The script uses `#!/bin/bash -e`, so a failed `dpkg -i /packages/libmali/...*.deb` command would abort the service.

## Risk Notes

Do not rerun the service blindly. On this rooted Scout, the expected first-boot package payload appears incomplete. Rerunning may leave graphics or power-management files partially moved, and it may not help a headless Auto-Scout runtime.

Potential future paths:

- If this service is not needed for the headless Scout workflow, consider disabling it and resetting its failed state.
- If the vendor platform setup is needed, recover the missing `/packages/libmali/*.deb` payload from the original image, run the setup once, and verify it creates `/usr/local/first_boot_flag`.
- Before changing it, confirm whether the missing Mali libraries affect camera/video, vendor UI, or any hardware acceleration used by Moorebot services.
