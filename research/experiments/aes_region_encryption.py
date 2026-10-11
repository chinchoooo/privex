import cv2
import numpy as np
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# =========================
# Key Derivation
# =========================
def derive_key(password: str) -> bytes:
    return hashlib.sha256(password.encode()).digest()

# =========================
# AES Encrypt Patch
# =========================
def encrypt_patch(patch: np.ndarray, password: str) -> np.ndarray:
    key = hashlib.sha256(password.encode()).digest()
    iv = key[:16]

    cipher = AES.new(key, AES.MODE_CBC, iv)

    h, w, c = patch.shape
    raw = patch.tobytes()

    # Ensure size multiple of 16
    if len(raw) % 16 != 0:
        raise ValueError("ROI size must be multiple of 16 bytes")

    encrypted = cipher.encrypt(raw)

    return np.frombuffer(encrypted, dtype=np.uint8).reshape((h, w, c))

# =========================
# AES Decrypt Patch
# =========================
def decrypt_patch(patch: np.ndarray, password: str) -> np.ndarray:
    key = hashlib.sha256(password.encode()).digest()
    iv = key[:16]

    cipher = AES.new(key, AES.MODE_CBC, iv)

    h, w, c = patch.shape
    raw = patch.tobytes()

    decrypted = cipher.decrypt(raw)

    return np.frombuffer(decrypted, dtype=np.uint8).reshape((h, w, c))

# =========================
# Create Sample Image With Text
# =========================
def create_sample_image():
    img = np.ones((400, 800, 3), dtype=np.uint8) * 255

    cv2.putText(img, "BANK ACCOUNT: 9876543210",
                (50, 150),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (0, 0, 0),
                3,
                cv2.LINE_AA)

    cv2.putText(img, "CONFIDENTIAL",
                (50, 250),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (0, 0, 255),
                3,
                cv2.LINE_AA)

    return img

# =========================
# Encrypt Region
# =========================
def encrypt_region(image, x, y, w, h, password):

    total_bytes = w * h * 3
    remainder = total_bytes % 16

    if remainder != 0:
        reduction_pixels = remainder // 3
        w = w - reduction_pixels

    roi = image[y:y+h, x:x+w].copy()

    encrypted = encrypt_patch(roi, password)
    image[y:y+h, x:x+w] = encrypted

    return image


# =========================
# Decrypt Region
# =========================
def decrypt_region(image, x, y, w, h, password):
    roi = image[y:y+h, x:x+w].copy()
    decrypted = decrypt_patch(roi, password)
    image[y:y+h, x:x+w] = decrypted
    return image

# =========================
# Main Test
# =========================
if __name__ == "__main__":

    password = "MY_SECRET_KEY"

    print("Character Key:", password)

    derived = hashlib.sha256(password.encode()).hexdigest()
    print("Derived AES-256 Key (SHA-256 hex):", derived)

    img = create_sample_image()
    cv2.imwrite("original.png", img)

    # Encrypt the text area
    encrypted_img = img.copy()
    encrypted_img = encrypt_region(encrypted_img, 40, 100, 700, 120, password)
    cv2.imwrite("encrypted.png", encrypted_img)

    # Decrypt back
    decrypted_img = encrypted_img.copy()
    decrypted_img = decrypt_region(decrypted_img, 40, 100, 700, 120, password)
    cv2.imwrite("decrypted.png", decrypted_img)

    print("\nSaved:")
    print("original.png")
    print("encrypted.png")
    print("decrypted.png")