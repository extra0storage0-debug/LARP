//! Compiled versions of Sentry's hottest pure maths, called from Python through ctypes.
//!
//! Each function mirrors a Python original that stays in the game as the fallback, and
//! tests/test_native.py checks the two agree. Nothing here touches the engine or game state, and
//! there are no dependencies: this PC's Smart App Control blocks the build scripts that PyO3 and
//! Rayon need, while allowing this plain DLL. tools/build_native.py compiles it.

use std::collections::HashMap;
use std::slice;
use std::sync::RwLock;
use std::thread;

const CHUNK_SIZE: f64 = 500.0;
const PARALLEL_FROM: usize = 2000; // below this, starting threads costs more than it saves
const MAX_THREADS: usize = 8;

#[derive(Clone, Copy)]
struct Crater {
    x: f64,
    z: f64,
    radius: f64,
    depth: f64,
}

struct Field {
    water_level: f64,
    sun: [f64; 3],
    extent: f64,
    craters: Option<HashMap<(i64, i64), Vec<Crater>>>,
}

// One island at a time, as in the game. Readers never wait on each other.
static FIELD: RwLock<Field> = RwLock::new(Field { water_level: 0.0, sun: [0.0, 1.0, 0.0], extent: 5000.0, craters: None });

#[inline]
fn footprint(x: f64, z: f64) -> f64 {
    let a = x.abs() / 5000.0;
    let b = z.abs() / 5000.0;
    (a * a) * (a * a) + (b * b) * (b * b)
}

#[inline]
fn crater_delta(distance: f64, radius: f64, depth: f64) -> f64 {
    let radius = radius.max(0.01);
    let depth = depth.max(0.0);
    let radial = distance.max(0.0) / radius;
    if radial >= 1.25 {
        return 0.0;
    }
    let bowl = if radial < 1.0 {
        let inner = 1.0 - radial * radial;
        -depth * inner * inner
    } else {
        0.0
    };
    let across = (radial - 0.86) / 0.11;
    let rim = depth * 0.24 * (-(across * across)).exp();
    let fade = if radial <= 1.0 { 1.0 } else { ((1.25 - radial) / 0.25).max(0.0) };
    bowl + rim * fade
}

impl Field {
    #[inline]
    fn base(&self, x: f64, z: f64) -> f64 {
        let value = footprint(x, z);
        if value >= 1.0 {
            return self.water_level;
        }
        let coast = (1.0 - value.sqrt()).max(0.0);
        let beach = (coast / 0.055).min(1.0).max(0.0);
        let rolling = 9.0 * (x * 0.0021 + z * 0.0013).sin()
            + 7.0 * (z * 0.0018 - x * 0.0011).cos()
            + 3.5 * ((x + z) * 0.0052).sin();
        let east = (x - 1450.0) / 1800.0;
        let north = (z - 2900.0) / 2000.0;
        let mountain = 245.0 * (-(east * east + north * north) * 1.55).exp();
        let interior = (24.0 + rolling + mountain).max(4.0) * (coast / 0.18).min(1.0);
        (beach * 3.0 + interior * (1.0 - beach) + beach * rolling * 0.12).min(330.0).max(0.0)
    }

    #[inline]
    fn height(&self, x: f64, z: f64) -> f64 {
        let mut height = self.base(x, z);
        if let Some(craters) = &self.craters {
            let cx = (x / CHUNK_SIZE).floor() as i64;
            let cz = (z / CHUNK_SIZE).floor() as i64;
            for ix in cx - 1..cx + 2 {
                for iz in cz - 1..cz + 2 {
                    if let Some(bucket) = craters.get(&(ix, iz)) {
                        for crater in bucket {
                            let dx = x - crater.x;
                            let dz = z - crater.z;
                            height += crater_delta((dx * dx + dz * dz).sqrt(), crater.radius, crater.depth);
                        }
                    }
                }
            }
        }
        height.max(-2.0)
    }

    fn paint(&self, x: f64, z: f64, height: f64) -> u32 {
        const PROBE: f64 = 9.0;
        let slope_x = (self.base(x + PROBE, z) - height) / PROBE;
        let slope_z = (self.base(x, z + PROBE) - height) / PROBE;
        let scale = 1.0 / (slope_x * slope_x + slope_z * slope_z + 1.0).sqrt();
        let [sun_x, sun_y, sun_z] = self.sun;
        let lit = ((-slope_x * sun_x + sun_y - slope_z * sun_z) * scale).max(0.0);
        let steep = 1.0 - scale;

        let mut patch = ((x * 0.0037 + z * 0.0021).sin() * (z * 0.0043 - x * 0.0017).cos()
            + 0.45 * (x * 0.017 - z * 0.013).sin())
            * 0.5
            + 0.5;
        patch = patch.min(1.0).max(0.0);
        patch = patch * patch * (3.0 - 2.0 * patch);
        let mut red = 62.0 + (134.0 - 62.0) * patch;
        let mut green = 108.0 + (152.0 - 108.0) * patch;
        let mut blue = 54.0 + (66.0 - 54.0) * patch;
        if height > 120.0 {
            let high = ((height - 120.0) / 110.0).min(1.0);
            red += (96.0 - red) * high;
            green += (120.0 - green) * high;
            blue += (92.0 - blue) * high;
        }
        let rock = ((steep - 0.10) / 0.16).max(0.0).min(1.0);
        red += (136.0 - red) * rock;
        green += (122.0 - green) * rock;
        blue += (108.0 - blue) * rock;
        let sand = ((footprint(x, z) - 0.90) / 0.055).max(0.0).min(1.0);
        red += (226.0 - red) * sand;
        green += (202.0 - green) * sand;
        blue += (158.0 - blue) * sand;

        let light = 0.66 + 0.52 * lit;
        let warmth = lit * 0.10;
        let channel = |value: f64| value.min(255.0).max(0.0) as u32;
        channel(red * light * (1.0 + warmth)) << 16
            | channel(green * light) << 8
            | channel(blue * light * (1.0 - warmth * 0.9 + (1.0 - lit) * 0.12))
    }
}

fn read() -> std::sync::RwLockReadGuard<'static, Field> {
    FIELD.read().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Run `work` over (x, z) pairs into `out`, on several threads if there are enough of them.
fn for_points<T: Send + Copy>(points: &[f64], out: &mut [T], work: impl Fn(f64, f64) -> T + Sync) {
    let count = out.len().min(points.len() / 2);
    let threads = thread::available_parallelism().map_or(1, |n| n.get()).min(MAX_THREADS);
    if count < PARALLEL_FROM || threads < 2 {
        for index in 0..count {
            out[index] = work(points[index * 2], points[index * 2 + 1]);
        }
        return;
    }
    let size = count / threads + 1;
    let work = &work;
    thread::scope(|scope| {
        for (out_part, in_part) in out[..count].chunks_mut(size).zip(points[..count * 2].chunks(size * 2)) {
            scope.spawn(move || {
                for (index, slot) in out_part.iter_mut().enumerate() {
                    *slot = work(in_part[index * 2], in_part[index * 2 + 1]);
                }
            });
        }
    });
}

#[no_mangle]
pub extern "C" fn sentry_terrain_setup(water_level: f64, sun_x: f64, sun_y: f64, sun_z: f64, extent: f64) {
    let mut field = FIELD.write().unwrap_or_else(|poisoned| poisoned.into_inner());
    *field = Field { water_level, sun: [sun_x, sun_y, sun_z], extent, craters: None };
}

/// Replace every crater, from `count` runs of (chunk x, chunk z, x, z, radius, depth).
///
/// # Safety
/// `data` must point to `count * 6` doubles.
#[no_mangle]
pub unsafe extern "C" fn sentry_set_craters(data: *const f64, count: usize) {
    let mut craters: HashMap<(i64, i64), Vec<Crater>> = HashMap::new();
    if count > 0 && !data.is_null() {
        for run in slice::from_raw_parts(data, count * 6).chunks_exact(6) {
            craters.entry((run[0] as i64, run[1] as i64)).or_default().push(Crater {
                x: run[2],
                z: run[3],
                radius: run[4],
                depth: run[5],
            });
        }
    }
    let mut field = FIELD.write().unwrap_or_else(|poisoned| poisoned.into_inner());
    field.craters = if craters.is_empty() { None } else { Some(craters) };
}

#[no_mangle]
pub extern "C" fn sentry_base_height(x: f64, z: f64) -> f64 {
    read().base(x, z)
}

#[no_mangle]
pub extern "C" fn sentry_height(x: f64, z: f64) -> f64 {
    read().height(x, z)
}

/// The height of the rendered terrain cell at a point, so grass sits on the mesh.
#[no_mangle]
pub extern "C" fn sentry_surface_height(x: f64, z: f64, steps: i64) -> f64 {
    let field = read();
    let extent = field.extent;
    let step = extent * 2.0 / steps as f64;
    let cell = |value: f64| (((value + extent) / step) as i64).max(0).min(steps - 1);
    let x0 = -extent + cell(x) as f64 * step;
    let z0 = -extent + cell(z) as f64 * step;
    let u = (x - x0) / step;
    let v = (z - z0) / step;
    let h00 = field.height(x0, z0);
    let h01 = field.height(x0, z0 + step);
    let h11 = field.height(x0 + step, z0 + step);
    let h10 = field.height(x0 + step, z0);
    if u <= v {
        (1.0 - v) * h00 + (v - u) * h01 + u * h11
    } else {
        (1.0 - u) * h00 + v * h11 + (u - v) * h10
    }
}

/// One colour, packed as 0xRRGGBB. `height` is the ground height used for slope and altitude.
#[no_mangle]
pub extern "C" fn sentry_paint(x: f64, z: f64, height: f64) -> u32 {
    read().paint(x, z, height)
}

/// Colours at `count` (x, z) points of the unmarked ground, on every core when worthwhile.
///
/// # Safety
/// `points` must hold `count * 2` doubles and `out` must hold `count` values.
#[no_mangle]
pub unsafe extern "C" fn sentry_paint_many(points: *const f64, count: usize, out: *mut u32) {
    let field = read();
    let field = &*field;
    for_points(slice::from_raw_parts(points, count * 2), slice::from_raw_parts_mut(out, count), |x, z| {
        field.paint(x, z, field.base(x, z))
    });
}

/// Heights at `count` (x, z) points, on every core when worthwhile.
///
/// # Safety
/// `points` must hold `count * 2` doubles and `out` must hold `count` values.
#[no_mangle]
pub unsafe extern "C" fn sentry_heights(points: *const f64, count: usize, out: *mut f64) {
    let field = read();
    let field = &*field;
    for_points(slice::from_raw_parts(points, count * 2), slice::from_raw_parts_mut(out, count), |x, z| {
        field.height(x, z)
    });
}

/// Sentry's cape: the wind-blown copy of the grid, then its edge trim.
///
/// # Safety
/// `original` and `moved` must hold `rows * cols * 3` doubles, `trim` must hold `rows * 12`.
#[no_mangle]
pub unsafe extern "C" fn sentry_cape(
    original: *const f64,
    rows: usize,
    cols: usize,
    time: f64,
    wind: f64,
    airflow_forward: f64,
    airflow_right: f64,
    moved: *mut f64,
    trim: *mut f64,
) {
    if rows == 0 || cols < 2 {
        return;
    }
    let original = slice::from_raw_parts(original, rows * cols * 3);
    let moved = slice::from_raw_parts_mut(moved, rows * cols * 3);
    let trim = slice::from_raw_parts_mut(trim, rows * 12);
    let forward = (airflow_forward / 520.0).min(0.34).max(-0.34);
    let right = (airflow_right / 520.0).min(0.22).max(-0.22);
    let last_row = (rows.max(2) - 1) as f64;
    for row in 0..rows {
        let row_alpha = row as f64 / last_row;
        for col in 0..cols {
            let at = (row * cols + col) * 3;
            let wave = (time * 7.0 + col as f64 * 0.72 + row as f64 * 0.55).sin();
            moved[at] = original[at] + wave * 0.055 * wind * row_alpha;
            moved[at + 1] = original[at + 1];
            moved[at + 2] = original[at + 2] + forward * row_alpha + right * row_alpha
                - wave.abs() * 0.34 * wind * row_alpha
                - wave.max(0.0) * 0.045 * wind * row_alpha;
        }
    }
    let mut out = 0;
    for row in 0..rows {
        let base = row * cols;
        for (edge, inner) in [(base, base + 1), (base + cols - 1, base + cols - 2)] {
            let (x, y, z) = (moved[edge * 3], moved[edge * 3 + 1], moved[edge * 3 + 2] - 0.022);
            trim[out..out + 6].copy_from_slice(&[x, y, z, x + (moved[inner * 3] - x) * 0.24, y, z]);
            out += 6;
        }
    }
}
