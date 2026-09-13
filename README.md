# BallastConverter

Converts scanned colour negatives into positives. It reads 16-bit TIFF scans and Hasselblad/Imacon
3f/fff files, inverts them with per-channel film gammas from a table of more than 300 films, and writes
a 16-bit TIFF with an embedded working colour space, ready for the final touches in Photoshop.

The idea: do the one step that Photoshop cannot do well, the inversion with the right gradation per
colour layer, and leave everything else (white point, grey balance, contrast) to the tools you already use.

## Download

Every commit on `main` is built automatically for Windows. Get `BallastConverter.exe` from the
[Releases](../../releases) page. Nothing to install: the file contains Python, the GUI and the ICC profiles.
Windows SmartScreen may warn about an unsigned application; choose "More info" and "Run anyway".

Settings are kept in `%USERPROFILE%\.ballastconverter.json`.

## Run from source (Windows, macOS, Linux)

```
pip install -r requirements.txt
python ballastconverter_gui.py
```

Python 3.10 or newer with tkinter. `sv-ttk` is optional (modern dark look); without it the GUI uses the
classic theme.

## Using the GUI

1. **Negative scan**: choose the TIFF or 3f/fff file. The output name is suggested as `<name>_positive.tif`.
2. **Input profile**: for 3f/fff files the scanner profile named in the file is selected automatically
   (marked "from the file's metadata"). For linearly scanned TIFFs choose `linear`. Other profiles can be picked
   with "…".
3. **Output profile**: the RGB working colour space of the result (Adobe RGB by default; sRGB and ProPhoto RGB
   are included). Its tone curve is used for encoding and the profile is embedded in the TIFF.
4. **Film**: pick the film. The three gammas come from the table. Choose "Manual" to edit them; the values of
   the last selected film remain as a starting point.
5. **Frame**: drag a green frame on the preview around the image only, without the film rebate and the
   perforation. White and black point are determined from this area; the output is always the whole image.
   Convert stays disabled until a frame is set.
6. **Exposure**: in stops, `+` brighter, `−` darker. `−1` leaves one stop of headroom so that no highlights are
   clipped; pull the white point up in Photoshop afterwards.
7. **White point / Black point**: the percentage of the densest and thinnest pixels inside the frame that is
   skipped when the anchors are set (protection against dust and scratches). Default 0.1.
8. **Convert** writes the full-resolution 16-bit TIFF.

The preview updates live with every change. Every control has a tooltip.

### Finishing in Photoshop

Open the TIFF in 16 bit. Levels: grey eyedropper on a neutral area, then raise the white point. If a single
channel needs more or less contrast, use the Levels midtone slider on that channel; it is mathematically the
same as changing that channel's film gamma. Nothing is lost as long as the file was converted with headroom.

## Command line

`ballastconverter.py` works without the GUI:

```
python ballastconverter.py --list-films
python ballastconverter.py scan.fff positive.tif --film "Kodak/Portra 400 (2026)" --in-curve "icc:Flextight X5 & 949" --stats-crop 700 500 7200 10600 --black 1
python ballastconverter.py scan.tif positive.tif --gammas 1.84 1.81 1.57 --out-curve icc:sRGB.icc
```

`--black 1` equals Exposure −1 in the GUI. `--p-black` and `--p-bpoint` are the white and black point
percentiles as fractions (0.001 = 0.1 %). `--stats-crop` is the frame in pixels of the original image.
`--help` lists everything.

## Profiles

The folder `profiles` contains the working colour spaces (Adobe RGB, sRGB, ProPhoto RGB) and the scanner
profiles of the Hasselblad/Imacon Flextight series. Any `.icc`/`.icm` file dropped into this folder appears in
the GUI: scanner profiles (class `scnr`) in the input list, RGB working colour spaces (class `mntr`) in the
output list. On the command line a profile can be given by name; the folder is searched automatically.

## How it works

Per channel, the densest point of the negative inside the frame becomes white and the thinnest point becomes
black. In between, the scanner value is inverted with a power function whose exponent is the film's gamma for
that colour layer, the reciprocal of the slope of its characteristic curve. Because each layer of a colour
negative has a different gradation, the three gammas differ, and that is what makes the colours come out right
without manual per-channel correction. The remaining per-channel offset at the thinnest point (the orange mask)
is subtracted so that the deepest shadows are neutral black.

The percentile anchors and the exposure only scale and shift the result; they never change the shape of the
curves. That is why every one of these settings can still be corrected losslessly in Photoshop, provided the
file is 16 bit and nothing was clipped.

## Building the Windows executable yourself

```
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name BallastConverter --add-data "profiles;profiles" --collect-all sv_ttk --hidden-import imagecodecs --hidden-import tifffile ballastconverter_gui.py
```

The GitHub Actions workflow in `.github/workflows/release.yml` does exactly this on every push and attaches
the result to a release. A tag such as `v1.0` produces a regular release; other commits produce pre-releases
named `build-<n>`. The version is shown in the GUI's status line at start and by `ballastconverter.py --version`.

## License

MIT, see `LICENSE`.
