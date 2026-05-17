import os
from PIL import Image

# Adjust these sizes to match your actual display dimensions
TARGET_SIZES = {
    'logo.png': (455, 303),      # from your Lighthouse warning
    'favicon.png': (32, 32),
    'favicon2.png': (64, 64),
}

def convert_images_if_needed(static_folder='static/data'):
    """
    Convert PNG images to WebP if the WebP file is missing or older than the PNG.
    Uses absolute path based on this script's location.
    """
    # Get the directory where this script is located (project root)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    img_folder = os.path.join(base_dir, static_folder)

    if not os.path.isdir(img_folder):
        print(f"Folder not found: {img_folder}. Skipping image conversion.")
        return

    for filename in os.listdir(img_folder):
        if not filename.lower().endswith('.png'):
            continue

        png_path = os.path.join(img_folder, filename)
        webp_filename = os.path.splitext(filename)[0] + '.webp'
        webp_path = os.path.join(img_folder, webp_filename)

        # Convert if WebP doesn't exist or is older than PNG
        if not os.path.exists(webp_path) or os.path.getmtime(webp_path) < os.path.getmtime(png_path):
            try:
                img = Image.open(png_path)
                if filename in TARGET_SIZES:
                    img.thumbnail(TARGET_SIZES[filename], Image.Resampling.LANCZOS)
                img.save(webp_path, 'webp', quality=85, optimize=True)
                print(f"Converted {filename} → {webp_filename}")
            except Exception as e:
                print(f"Error converting {filename}: {e}")