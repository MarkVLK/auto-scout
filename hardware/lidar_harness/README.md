# LD19 LiDAR Harness

Parametric mount that carries an LD19-class 2D LiDAR on top of the Moorebot Scout.

## Read this first

**This is a template, not a verified part.** No one has measured this Scout's top shell
or this particular LD19 unit, so every dimension tagged `MEASURE` in
[`scout_ld19_harness.scad`](scout_ld19_harness.scad) is currently a placeholder. Printing
it as-shipped will almost certainly produce a part that does not fit.

The model is still worth having, because it encodes the constraints that actually matter
and turns the job into "fill in eight measurements" rather than "design a mount." Work
through the worksheet below, print the fit check, then print the real thing.

## Design constraints this model enforces

- **Clean 360 degrees.** The scan plane must sit above the tallest point on the Scout —
  the camera turret. If it does not, the robot permanently sees itself as an obstacle at
  close range and `move_base` will refuse to move. The riser height is derived from
  `target_scan_plane_above_shell`, and preview mode draws the scan plane as a disc so you
  can eyeball the clearance before printing.
- **No drilling.** The saddle is concave to match the shell and is held by two straps,
  with foam/EVA tape as the compliant interface. `saddle_liner_gap` reserves room for it.
- **Cable strain relief.** A channel routes the 4-wire UART harness (VDD / GND / LD19-TX
  to Scout-RX) down through the hollow riser and out the rear, with a zip-tie bridge, so
  robot motion cannot shift or unplug the sensor. This is an explicit open item in
  [`docs/AUTO_SCOUT_CHECKLIST.md`](../../docs/AUTO_SCOUT_CHECKLIST.md).
- **A measurable URDF offset.** The console output prints the scan-plane height above the
  shell contact point, which feeds directly into the `base_to_laser` joint in
  [`urdf/scout.urdf`](../../urdf/scout.urdf). That transform is currently a placeholder
  (`xyz="0.1 0 0.05"`, which puts the LiDAR ahead of the robot's front edge) and **must**
  be replaced with the real number once the harness exists.

## Measurement worksheet

Calipers and a straightedge. Record values here, then edit the `.scad`.

### LiDAR

| Parameter | What to measure | Yours |
| --- | --- | --- |
| `lidar_base_dia` | Diameter of the base where it contacts a flat surface | |
| `lidar_bolt_positions` | `[x, y]` of each mounting hole relative to the rotor centre | |
| `lidar_bolt_dia` | Screw clearance: 2.3 for M2, 2.8 for M2.5 | |
| `lidar_scan_plane_z` | Mounting face up to the middle of the optical window | |
| `lidar_cable_slot_w` / `_l` | Connector + wire bundle envelope where it exits | |
| `lidar_cable_angle` | Which way the cable leaves, degrees; 180 = rearward | |

LD19-class units ship with two or four mounting holes and the pattern varies between
vendors, so measure rather than trusting a datasheet you found for a similar model.

### Scout top shell

| Parameter | What to measure | Yours |
| --- | --- | --- |
| `shell_radius_x` | Fore-aft curvature of the landing patch | |
| `shell_radius_y` | Side-to-side curvature of the landing patch | |
| `saddle_len` / `saddle_wid` | Footprint, kept clear of vents, turret, dock contacts | |
| `target_scan_plane_above_shell` | Turret height above the landing patch, **plus 10 mm** | |

To get a curvature radius: lay a straightedge across the shell, measure the span and the
sag at the middle, then `R = span^2 / (8 * sag) + sag / 2`. For a nearly flat patch, use a
large number such as 500.

### Mounting position

Also record, for the URDF:

- **Fore-aft offset** of the saddle's centre from the Scout's rotation centre (`+x` forward).
- **Lateral offset** (`+y` left). Aim for zero; a laser offset in `y` that AMCL does not
  know about will bias localisation.
- **Height** of the shell contact point above the robot's rotation centre.
- **Yaw** of the LiDAR's zero-degree mark relative to the robot's forward direction.

## Printing

1. Open in OpenSCAD, set `part = "assembly"`, and check the ghost scan plane clears
   everything on the robot.
2. Set `part = "fitcheck"` and print that first — it is the saddle profile plus the bolt
   pattern only, a few grams and a few minutes. Confirm it seats on the shell and the
   LiDAR bolts line up before committing to a full print.
3. Set `part = "printable"` and export. This orientation puts the flat plate face on the
   bed and the dome upward, which avoids supports under the concave pocket.

Suggested settings: PETG or ABS (PLA creeps and can sag near a warm robot), 0.2 mm layers,
4 perimeters, 30–40% infill. The riser carries a spinning mass, so favour walls over infill.

## After it is installed

The harness is the gate on everything scan-dependent. Once it is on the robot:

1. Re-measure and update `base_to_laser` in `urdf/scout.urdf`.
2. Re-enable the sensor: `AUTO_SCOUT_ENABLE_LIDAR=true`, then `AUTO_SCOUT_ENABLE_NAV_STACK=true`
   only after `/scan` is confirmed.
3. Work through the scan-gated section of
   [`docs/BRINGUP_ROADMAP.md`](../../docs/BRINGUP_ROADMAP.md).
