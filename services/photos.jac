import from services.session { current_session }
import from services.promo { _lock, _unlock }
import from services.media_upload { save_photo }
import from services.photo_reference { image_reference }

obj PhotoResult { has ok: bool = False, url: str = "", message: str = ""; }

def:protect upload_business_photo(payload: str) -> PhotoResult {
    session = current_session();
    if not session.authenticated or session.role not in ["business", "merchant"] {
        return PhotoResult(message="Sign in with a business account to upload a photo.");
    }
    fd = _lock();
    try {
        try { return PhotoResult(ok=True, url=save_photo(payload, session.actor_id)); }
        except ValueError as error { return PhotoResult(message=str(error)); }
        except Exception { return PhotoResult(message="Could not upload the photo. Your current photo is kept; try again."); }
    } finally { _unlock(fd); }
}

def:protect import_business_photo(url: str) -> PhotoResult {
    session = current_session();
    if not session.authenticated or session.role not in ["business", "merchant"] {
        return PhotoResult(message="Sign in with a business account to choose a photo.");
    }
    fd = _lock();
    try {
        try { return PhotoResult(ok=True, url=image_reference(url, session.actor_id)); }
        except ValueError as error { return PhotoResult(message=str(error)); }
        except Exception { return PhotoResult(message="Could not import this photo. Your selected photo is kept; upload one instead."); }
    } finally { _unlock(fd); }
}
