import argparse
import cv2
import numpy as np


def remove_background(input_path, output_path, iter_count=5):
    image = cv2.imread(input_path)
    if image is None:
        raise FileNotFoundError(f"Input image {input_path} not found")

    mask = np.zeros(image.shape[:2], np.uint8)

    # Initialize background and foreground models
    bgdModel = np.zeros((1, 65), np.float64)
    fgdModel = np.zeros((1, 65), np.float64)

    # Define initial rectangle for GrabCut (whole image)
    rect = (1, 1, image.shape[1]-2, image.shape[0]-2)

    # Apply GrabCut
    cv2.grabCut(image, mask, rect, bgdModel, fgdModel, iter_count, cv2.GC_INIT_WITH_RECT)

    # Convert mask to binary where sure or likely foreground are 1, else 0
    mask2 = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype('uint8')

    # Multiply mask with input image to get result
    img_fg = image * mask2[:, :, np.newaxis]

    # Create alpha channel from mask
    alpha = mask2 * 255
    result = np.dstack((img_fg, alpha))

    cv2.imwrite(output_path, result)


def main():
    parser = argparse.ArgumentParser(description='Remove background from image using GrabCut.')
    parser.add_argument('input', help='Input image file path')
    parser.add_argument('output', help='Output image file path (PNG with alpha channel)')
    parser.add_argument('--iter', type=int, default=5, help='Number of GrabCut iterations')
    args = parser.parse_args()

    remove_background(args.input, args.output, args.iter)


if __name__ == '__main__':
    main()
