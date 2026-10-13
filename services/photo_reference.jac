import from services.media_upload { owned_photo, save_image_bytes }
import from services.website_import { clean_url, fetch_public }

def image_reference(value: str, actor: str) -> str {
    if not value { return ""; }
    if value.startswith("/static/photos/") { return owned_photo(value, actor); }
    (source, mime, data) = fetch_public(clean_url(value));
    if mime not in ["image/jpeg", "image/png", "image/webp"] {
        raise ValueError("Choose a JPG, PNG or WebP website photo, or upload one from your phone.");
    }
    return save_image_bytes(data, actor);
}
