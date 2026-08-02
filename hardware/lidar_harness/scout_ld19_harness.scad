// =====================================================================
// Auto-Scout - LD19 LiDAR harness for the Moorebot Scout
// =====================================================================
//
// STATUS: PARAMETRIC TEMPLATE, NOT A VERIFIED DROP-IN PART.
//
// Every dimension tagged "MEASURE" below is a placeholder that has NOT
// been checked against real hardware. Nobody has measured this Scout's
// top shell or this specific LD19 unit. Print the FIT CHECK part first
// (part = "fitcheck"), confirm it sits on the robot and that the LiDAR
// bolts line up, and only then print the full harness.
//
// See README.md in this directory for the measurement worksheet.
//
// Design intent:
//   - Lift the LD19 scan plane above every obstruction on the Scout,
//     including the camera turret, so the sensor gets a clean 360 deg.
//   - Mount without drilling the Scout: a concave saddle conforming to
//     the top shell, held by two straps, with foam tape as the interface.
//   - Route and strain-relieve the 4-wire UART harness (VDD/GND/TX/RX)
//     so robot motion cannot shift or unplug the sensor.
//   - Produce a repeatable, measurable base_link -> base_laser offset
//     that can be written straight back into urdf/scout.urdf.
//
// Units: millimetres.
// =====================================================================


/* [What to render] */
// assembly  - full harness as it mounts
// printable - full harness rotated for printing (plate on the bed)
// fitcheck  - thin, fast-printing test of the saddle + bolt pattern only
// saddle    - saddle only
// plate     - LiDAR plate only
part = "assembly"; // [assembly, printable, fitcheck, saddle, plate]

// Show a ghost LiDAR body and its scan plane (preview only, not exported)
show_ghost = true;


/* [LiDAR - MEASURE YOURS] */

// Diameter of the LD19 base where it contacts the plate.
lidar_base_dia = 38.6;                         // MEASURE

// Mounting hole positions in the LiDAR base, relative to the centre of
// its rotor, in [x, y] mm. LD19-class units ship with either two or four
// holes and the pattern varies between vendors - measure yours and edit
// this list. Add or remove entries freely.
lidar_bolt_positions = [ [-15, 0], [15, 0] ];  // MEASURE

// Clearance hole for the mounting screws. 2.3 suits M2, 2.8 suits M2.5.
lidar_bolt_dia = 2.3;                          // MEASURE

// Height of the spinning scan plane above the LiDAR's own mounting face.
// This is the number that decides how tall the harness must be. Measure
// from the flat face that touches the plate up to the middle of the
// rotor's optical window.
lidar_scan_plane_z = 18.0;                     // MEASURE

// Cable exit: width and depth of the slot that clears the connector and
// wires leaving the underside/side of the LiDAR.
lidar_cable_slot_w = 11.0;                     // MEASURE
lidar_cable_slot_l = 7.0;                      // MEASURE

// Which way the cable leaves the LiDAR, in degrees around the plate.
// 180 = towards the rear of the Scout.
lidar_cable_angle = 180;                       // MEASURE


/* [Scout top shell - MEASURE YOURS] */

// The Scout's top is domed. These are the radii of curvature of the
// landing patch, fore-aft (X) and side-to-side (Y). Lay a straightedge
// across the shell, measure the sag over a known span, and solve
// R = (span^2)/(8*sag) + sag/2. For a nearly flat patch use a big number
// such as 500.
shell_radius_x = 90;                           // MEASURE
shell_radius_y = 70;                           // MEASURE

// Footprint of the saddle on the shell. Keep it inside the flat-ish
// landing zone and clear of vents, the camera turret, and the dock
// contacts.
saddle_len = 70;                               // MEASURE
saddle_wid = 58;                               // MEASURE

// How deep the concave pocket wraps down the sides of the shell.
saddle_grip_depth = 7;

// Wall thickness of the saddle shell.
saddle_wall = 2.6;

// Extra gap between the printed saddle and the shell, to be taken up by
// foam/EVA tape. Increase if you want a thicker liner.
saddle_liner_gap = 1.0;


/* [Scan clearance - MEASURE YOURS] */

// Height of the LiDAR scan plane above the saddle's lowest contact point
// on the shell. This MUST clear the tallest thing on the Scout - the
// camera turret - by a real margin, or the robot will permanently see
// itself as an obstacle at close range. Measure the turret height above
// the landing patch and add at least 10 mm.
target_scan_plane_above_shell = 40;            // MEASURE

// Diameter of the riser column stack. Kept small so it never intrudes
// into the scan plane.
riser_dia = 26;

// Thickness of the plate the LiDAR bolts to.
plate_t = 3.2;


/* [Straps] */

// Two slots take a strap / velcro / heavy zip tie over the LiDAR mount
// and around the Scout body.
strap_w = 12.5;
strap_t = 3.0;
strap_slot_inset = 7;
enable_strap_slots = true;


/* [Cable management] */

// Channel through the saddle for the 4-wire UART harness back to the
// Scout's UART header, plus a zip-tie bridge for strain relief.
cable_channel_w = 7.0;
cable_channel_h = 5.0;
enable_strain_relief = true;


/* [Print] */
$fn = 96;
eps = 0.01;


// =====================================================================
// Derived geometry
// =====================================================================

plate_dia   = max(lidar_base_dia + 6, 30);
riser_h     = max(target_scan_plane_above_shell - lidar_scan_plane_z - plate_t, 4);
saddle_h    = saddle_grip_depth + saddle_wall;
plate_bot_z = saddle_h + riser_h;
plate_top_z = plate_bot_z + plate_t;
scan_z      = plate_top_z + lidar_scan_plane_z;


// Echo the numbers that matter so they show in the OpenSCAD console.
echo(str("riser height          = ", riser_h, " mm"));
echo(str("plate top face at z   = ", plate_top_z, " mm above shell contact"));
echo(str("scan plane at z       = ", scan_z, " mm above shell contact"));
echo(str("URDF base_to_laser z  = <shell contact height above base_link> + ", scan_z/1000, " m"));


// =====================================================================
// Modules
// =====================================================================

// Concave dome removed from the underside of the saddle. Approximates
// the Scout's doubly-curved top shell as an ellipsoid.
module shell_negative(extra = 0) {
    r = shell_radius_x + saddle_liner_gap + extra;
    translate([0, 0, r - saddle_grip_depth])
        scale([1, shell_radius_y / shell_radius_x, 1])
            sphere(r = r);
}

module saddle_blank() {
    hull() {
        translate([0, 0, saddle_h - eps])
            linear_extrude(height = eps)
                offset(r = 4)
                    square([saddle_len - 8, saddle_wid - 8], center = true);
        translate([0, 0, 0])
            linear_extrude(height = eps)
                offset(r = 6)
                    square([saddle_len - 12, saddle_wid - 12], center = true);
    }
}

module strap_slots() {
    for (sx = [-1, 1])
        translate([sx * (saddle_len / 2 - strap_slot_inset), 0, saddle_h / 2 + 1])
            cube([strap_t, strap_w, saddle_h + 10], center = true);
}

module cable_channel() {
    // Runs from under the riser out to the rear edge of the saddle.
    rotate([0, 0, lidar_cable_angle])
        translate([0, -cable_channel_w / 2, saddle_h - cable_channel_h])
            cube([saddle_len, cable_channel_w, cable_channel_h + eps]);
}

module strain_relief_bridge() {
    // A small arch over the cable channel to zip-tie the harness down.
    rotate([0, 0, lidar_cable_angle])
        translate([saddle_len / 2 - 12, 0, saddle_h - eps])
            difference() {
                translate([0, 0, 2.5])
                    cube([5, cable_channel_w + 8, 5], center = true);
                translate([0, 0, 2.5])
                    cube([5 + eps, cable_channel_w, 3.2], center = true);
            }
}

module saddle() {
    difference() {
        union() {
            saddle_blank();
            if (enable_strain_relief) strain_relief_bridge();
        }
        shell_negative();
        if (enable_strap_slots) strap_slots();
        cable_channel();
    }
}

module riser() {
    difference() {
        hull() {
            translate([0, 0, saddle_h - eps])
                cylinder(d = riser_dia + 8, h = eps);
            translate([0, 0, plate_bot_z - eps])
                cylinder(d = riser_dia, h = eps);
        }
        // Hollow core doubles as the cable route up to the LiDAR.
        translate([0, 0, saddle_h - saddle_wall])
            cylinder(d = riser_dia - 2 * saddle_wall, h = riser_h + saddle_wall + eps);
    }
}

module plate() {
    difference() {
        translate([0, 0, plate_bot_z])
            cylinder(d = plate_dia, h = plate_t);

        // LiDAR mounting holes
        for (p = lidar_bolt_positions)
            translate([p[0], p[1], plate_bot_z - eps])
                cylinder(d = lidar_bolt_dia, h = plate_t + 2 * eps);

        // Central pass-through for the connector and wires
        translate([0, 0, plate_bot_z - eps])
            cylinder(d = riser_dia - 2 * saddle_wall - 1, h = plate_t + 2 * eps);

        // Side notch so the cable can exit without fouling the rotor
        rotate([0, 0, lidar_cable_angle])
            translate([plate_dia / 2 - lidar_cable_slot_l / 2, 0, plate_bot_z - eps])
                cube([lidar_cable_slot_l, lidar_cable_slot_w, plate_t + 2 * eps], center = false);
    }
}

module harness() {
    union() {
        saddle();
        riser();
        plate();
    }
}

// Thin, fast test print: proves the saddle curvature and the bolt
// pattern without burning filament on the risers.
module fitcheck() {
    intersection() {
        saddle();
        translate([0, 0, -1]) cylinder(d = 400, h = saddle_h + 1);
    }
    translate([0, 0, saddle_h])
        difference() {
            cylinder(d = plate_dia, h = 2);
            for (p = lidar_bolt_positions)
                translate([p[0], p[1], -eps])
                    cylinder(d = lidar_bolt_dia, h = 2 + 2 * eps);
        }
}


// =====================================================================
// Preview aids (never part of an export)
// =====================================================================

module ghost_lidar() {
    %translate([0, 0, plate_top_z])
        cylinder(d = lidar_base_dia, h = lidar_scan_plane_z + 12);
    // Scan plane - nothing on the robot may intersect this disc.
    %translate([0, 0, scan_z])
        cylinder(d = 300, h = 0.6, center = true);
}


// =====================================================================
// Render
// =====================================================================

if (part == "assembly") {
    harness();
    if (show_ghost) ghost_lidar();
} else if (part == "printable") {
    // Flip so the flat plate face is on the bed and the dome faces up.
    translate([0, 0, plate_top_z]) rotate([180, 0, 0]) harness();
} else if (part == "fitcheck") {
    fitcheck();
} else if (part == "saddle") {
    saddle();
} else if (part == "plate") {
    translate([0, 0, -plate_bot_z]) plate();
}
