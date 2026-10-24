import io
import os
import uuid

from PIL import Image, ImageOps


ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def is_allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _open_image(image_file):
    image_file.seek(0)
    image = Image.open(image_file)
    image = ImageOps.exif_transpose(image)
    if image.mode not in ('RGB', 'L'):
        background = Image.new('RGB', image.size, (255, 255, 255))
        alpha = image.getchannel('A') if 'A' in image.getbands() else None
        background.paste(image, mask=alpha)
        image = background
    elif image.mode != 'RGB':
        image = image.convert('RGB')
    return image


def save_optimized_image(image_file, upload_folder, *, max_size=(1280, 1280), quality=78):
    image = _open_image(image_file)
    image.thumbnail(max_size, Image.LANCZOS)

    filename = f"{uuid.uuid4().hex}.jpg"
    file_path = os.path.join(upload_folder, filename)

    output = io.BytesIO()
    image.save(output, format='JPEG', quality=quality, optimize=True, progressive=True)
    with open(file_path, 'wb') as target:
        target.write(output.getvalue())

    return filename, file_path


def save_optimized_avatar(image_file, upload_folder):
    image = _open_image(image_file)
    image.thumbnail((512, 512), Image.LANCZOS)

    filename = f"{uuid.uuid4().hex}.jpg"
    file_path = os.path.join(upload_folder, filename)

    output = io.BytesIO()
    image.save(output, format='JPEG', quality=82, optimize=True, progressive=True)
    with open(file_path, 'wb') as target:
        target.write(output.getvalue())

    return filename, file_path
