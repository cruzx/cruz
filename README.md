# Background Removal Tool

`bg_remover.py` is a small command line utility that removes the background from an image using OpenCV's GrabCut algorithm.

## Requirements

- Python 3.8+
- `opencv-python`
- `numpy`

Install the dependencies via pip:

```bash
pip install opencv-python numpy
```

## Usage

```bash
python bg_remover.py input.jpg output.png
```

The output image is saved as a PNG with an alpha channel where the background has been made transparent. Use `--iter` to control the number of GrabCut iterations if needed.
