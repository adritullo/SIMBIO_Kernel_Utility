# SIMBIO Kernel Utility

Standalone desktop tool, based on open-source resources (Python, SpiceyPy, NumPy and PySide6) that interrogate BepiColombo **kernel** into quick answers
about mission time and SIMBIO-SYS observation geometry. The metakernel is loaded once (top bar, or drag & drop a `.tm`)
and feeds every windos tool (here referred as "cards").

## Quickstart
0. Download the standalone release you need from the ___Release___ section on the right of the page (and unzip it).  

(If you already have kernel downloaded just *jump directly to step 3*)
1. The tool work around metakernels to define which kernel file take in consideration. If you don't have your version you can search and download the official one using the Search Kernel card. The default url ("https://spiftp.esac.esa.int/data/SPICE/BEPICOLOMBO/kernels/mk/") will give you the official one automatically update by ESA. Press __Search__ to have the list of mk available at the moment, select the desired one and press "Download and use as metakernel" (or just "Dowload selected" if you don't intend to use it).
2. In the card "Kernel Download" select the destination folder you want to use and then ___Download kernels___. When finished the downloaded metakernel will be automatically addressed. You are ready to go (*jump to step 4*).
3. Browse the metakernel you want to use with ___Browse___ then ___Load___. The number of correct kernel file loaded will be show in the up-right corner in green.
4. The tools of the suite can be addressed directly from the list on the left part. 
5. The Time Converter permits to translate time in the UTC and Epoch format. Just write or paste the original in the correct form.
6. Observation Geometry permits to calculate the main information regarding the capacity of observation of the selected camera at the moment decided. A simple hillshade rendered in the lower part simulate the illumination condition and the And the ability to observe surface features as a function of resolution (roughly approximate). The arrows around the date permit respectively to jump 1 s, 1 m and 1 h backward or forward in time.

## Cards

| Card | What it does |
|---|---|
| **Time Converter** | UTC → ET (TDB s past J2000) and ET → UTC (ISO / day-of-year / TDB calendar, 0–6 decimals). Accepts ISO, `2027 APR 06 07:48:34`, `2027-096T…`, `2027-05-18 T02:10:30`. The two columns are **mirrored**: typing UTC on the left fills the ET on the right and vice versa (each with its own conversions); clearing or an invalid entry empties the other side. One click sends the epoch to the Geometry card. |
| **Observation Geometry** | Pick **Channel** (STC-H, STC-L, HRIC, VIHI…) and **Filter** (P700, F420, F550, FPAN…) — both lists are discovered from the loaded IK — plus an epoch (UTC or ET). Returns season (`APH1`, `D2N1`, …), MTA, ground resolution, flight altitude, orbital velocity, central-pixel lat/lon, sub-spacecraft lat/lon, solar incidence/azimuth, phase, emission (+ slant range). Optional **illustrative hillshade** flag. The epoch has **««« « ‹ › » »»»** buttons (∓1 s, ∓1 min, ∓1 h; hold to repeat; they recompute immediately) and the header shows the mission plan (**MTP n · STP m**). Tiles copy on click; *Copy all* / *Export…* (CSV, JSON). |
| **Search Kernel** | Lists every `*.tm` published in a server folder — default `https://spiftp.esac.esa.int/data/SPICE/BEPICOLOMBO/kernels/mk/` (editable; clear it to restore the default; http(s) and `ftp://` work, and an https listing that fails falls back to FTP on the same host/path). Shows type (latest operational / latest planning / versioned `vXXX · date #NNN`), modified date and size, with a text filter and a short description of `bc_ops.tm`, `bc_plan.tm` and `*_vXXX_YYYYMMDD_NNN.tm`. **Download selected** saves the chosen files (default folder `<output>/data/SPICE/BEPICOLOMBO/kernels/mk`); **Download and use as metakernel** (or double-click) saves one, puts it in the metakernel bar and loads it — if its kernels are not on the computer you land in *Kernel Download*. |
| **Kernel Download** | Downloads every kernel listed in the metakernel (top bar) from an anonymous FTP server — default `spiftp.esac.esa.int`, editable (also `host:port`; clear it to restore the default; **Test** checks the connection). Output folder + *Remote kernels path* (default `data/SPICE/BEPICOLOMBO/kernels`) reproduce the ESA tree under the output folder, and a copy of the metakernel with `PATH_VALUES` pointing to it is written to `…/kernels/mk/`. Works **without kernels being loaded** (they are not there yet). Existing files with the same size are skipped (*Re-download…* forces them), files are written as `.part` and renamed when complete, network errors are retried with a reconnect, one missing file does not stop the others, **Cancel** is immediate and leaves no partial files. A metakernel whose kernels are not (all) on disk is detected right after *Browse…* / *Load* / drag-and-drop and sends you to this card, with the output folder pre-filled when the metakernel already sits in `<out>/data/SPICE/BEPICOLOMBO/kernels/mk/`. When every file is on disk the new metakernel is put in the metakernel bar and **loaded automatically** (after errors the *Load the downloaded metakernel* button stays available). |

## Run from source

```
py -3 -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

## Build the .exe (Windows)

```
build_exe.bat            :: single file  -> dist\SimbioKernelUtility.exe
build_exe.bat onedir     :: folder       -> dist\SimbioKernelUtility\SimbioKernelUtility.exe (faster start-up)
```
The script creates a private `.venv`, runs the test-suite, then builds from `SimbioKernelUtility.spec` (icon, bundled example DTM, spiceypy's CSPICE DLL).

**Troubleshooting (start-up error `DLL load failed while importing QtWidgets`):** the usual causes are (1) PyInstaller bundling a foreign
`icuuc.dll`/`icudt*.dll` found on PATH (Anaconda, QGIS…) — the spec excludes ICU so Windows' own is used — and (2) an old Visual C++ runtime.
On failure the app writes `%TEMP%\SimbioKernelUtility_startup.log`. Older note: `ImportError: DLL load failed while importing QtWidgets: The specified procedure could not be found` means an older
`VCRUNTIME140.dll` (copied from the Python install) shadows the newer one PySide6 needs. The spec replaces it with the copy shipped in the
PySide6 wheel; if you ever see it again, rebuild from the spec (not a bare `pyinstaller run.py`) and check that `dist` was rebuilt with `--clean`.

## Build for macOS and Linux (and all three at once)
PyInstaller cannot cross-compile: build on the OS you target.

| Target | How | Result |
|---|---|---|
| Windows | `build_exe.bat` | `dist\SimbioKernelUtility.exe` |
| macOS | `bash build_app.sh` (Terminal, on a Mac) | `dist/SimbioKernelUtility.app` + `SimbioKernelUtility-<ver>-macos-<arch>.zip` |
| Linux | `bash build_app.sh [onedir]` (also works in WSL on Windows) | `dist/SimbioKernelUtility` + `…-linux-<arch>.tar.gz` |
| **All four at once** | push the repo to GitHub; `github_workflow_build.yml` (move it to `.github/workflows/build.yml`) builds Windows x64, macOS Apple Silicon, macOS Intel and Linux x64, runs the tests and the smoke test on each, and attaches the downloads to the run. Push a tag (`git tag v0.3.0 && git push --tags`) to also publish a GitHub Release. | 4 downloads |

Each OS keeps its own build environment (`.venv-win`, `.venv-linux-x86_64`, `.venv-macos-arm64`…), so the project folder can be shared
between machines (Syncthing, OneDrive…) without one OS breaking the other's virtual environment. The old shared `.venv` is no longer used and can be deleted.

Every build ends with `scripts/smoke_test.py`, which starts the **built** app in self-test mode (`SimbioKernelUtility --selftest out.txt`):
a window is created off-screen, CSPICE is loaded and every bundled resource (icon, both DTMs, EVF) is read. It prints `SELFTEST OK` or the traceback.

Icons: edit `simbio_utility/resources/icon.png` (256 px, square) and regenerate `icon.ico` (Windows) and `icon.icns` (macOS) with Pillow:
`python -c "from PIL import Image; im=Image.open('icon.png').convert('RGBA'); im.save('icon.ico', sizes=[(s,s) for s in (16,24,32,48,64,128,256)]); im.resize((512,512)).save('icon.icns')"`.

Platform notes
* **macOS**: unsigned apps are blocked by Gatekeeper on first launch — right-click → *Open*, or `xattr -cr SimbioKernelUtility.app` once. Signing/notarizing needs an Apple Developer ID. Build arm64 and Intel separately (the workflow does).
* **Linux**: Qt needs a few system libraries (`sudo apt install libxcb-cursor0 libegl1 libxkbcommon-x11-0`). Build on an older distro (the workflow uses Ubuntu 22.04) so the binary runs on newer ones. After unpacking, `chmod +x SimbioKernelUtility` if needed.
* Settings are stored per OS (registry / plist / `~/.config/INAF/`); the app and the card placeholders use each platform's own path style, and `~` is accepted in paths.

## Definitions (what each number means)

| Quantity | Definition |
|---|---|
| Central pixel | Camera **boresight** from the IK (`getfov`) intersected with the ellipsoid (`sincpt`), aberration correction from Settings (default `LT+S`). |
| Ground resolution | `slant range × IFOV / cos(emission)` in m/px; IFOV = pixel pitch / focal length (STC 10 µm / 95 mm, HRIC 10 µm / 800 mm, VIHI 40 µm / 160 mm — same table as `timefinder.py`; unknown channels fall back to the IK field of view). |
| Flight altitude | Distance spacecraft → nearest ellipsoid point (`subpnt`, NEAR POINT). *Slant range* (spacecraft → central pixel) is shown separately. |
| Orbital velocity | \|v\| of MPO relative to Mercury, J2000, no light-time correction. |
| Latitude / longitude | Planetocentric, east-positive (−180…180 or 0…360 in Settings). |
| Incidence, phase, emission | `illumf` (ellipsoid, Sun as source) at the central pixel. |
| Solar azimuth | Direction towards the Sun in the local horizon frame of the central pixel, clockwise from north, 0–360°. |
| MTA | True anomaly of **Mercury** around the Sun (`oscltx` on Mercury→Sun state in ECLIPJ2000, GM from the kernel pool). |
| Season | See below. |
| MTP / STP | From the event file (`.evf`): each `STP_START/STP_END (COUNT = n)` pair is STP *n*; **MTP = 4 consecutive STPs** (MTP1 = STP1–4, MTP2 = STP5–8 …). An STP lasts until the next one starts. Times are UTC. The built-in timeline is `stps_bc_sgs_PLANNING_20260306_MODIFICATO.evf` (147 STPs, 2027-03-14 → 2029-12-31); *Settings → STP / MTP timeline* loads another file (or *Built-in* to go back). Outside the file's span the tile shows “—”. |

### Season / number (**please confirm this convention**)
Mercury's year is split in four 90° sectors of MTA, starting at 135°:

| Sector | MTA | Label |
|---|---|---|
| Aphelion | 135° – 225° | `APHn` |
| Terminator after aphelion | 225° – 315° | `D2Nn` |
| Perihelion | 315° – 045° | `PERn` |
| Terminator before next aphelion | 045° – 135° | `N2Dn` |

`n` counts Mercury years from the science-phase aphelion (`APH0` ≈ 2027-03-22); `D2N1/PER1/N2D1` follow `APH1` and precede `APH2`.
The 135°/225° limits reproduce the APH windows of the mission table in `timefinder.py` (APH1 = 2027-06-02 … 07-03).
Everything (limits, names, epoch) can be changed with a JSON file — see `seasons.example.json`, then *Settings → Season definition*.

### Hillshade
**Scale DTM to ground resolution** (on by default): the DTM is resampled so one pixel equals the instrument ground resolution of the computed geometry (block-average, then bilinear for the fractional part), so craters, slopes and cast-shadow lengths appear at the size the camera can resolve. If the instrument is finer than the DTM the DTM stays native (e.g. the STC DTM is 118 m/px, the HRIC one 5 m/px). Off = original DTM pixel size. Magnified previews show true (blocky) pixels.

Two reference DTMs are bundled: `exampleDTM_HRIC.tif` (5 m/px) and `exampleDTM_STC.tif` (118 m/px). The field switches automatically when the *channel* changes — HRIC → the HRIC DTM, STC-H / STC-L / VIHI → the STC DTM — and the new file is used at the next Compute. Choosing another file (`…` or typing the path) is remembered per family; clearing the field restores the bundled DTM. A DTM is auto-averaged to ≤ 1400 px when not scaled, and is **only a generic reference relief**: it is never
placed on Mercury, and the picture says so. Lambertian shading uses the computed solar azimuth and incidence (`n·s`), with optional
approximate cast shadows (horizon sampling towards the Sun). Night side (incidence ≥ 90°) renders black. Pick another GeoTIFF with the `…` button.
Compressed GeoTIFFs other than none/DEFLATE need `pip install imagecodecs` (not bundled, to keep the exe small).