import bcrypt
import secrets

def hash_password(password: str) -> str:
    """
    Genera un hash seguro de la contraseña usando bcrypt
    """
    # Convertir a bytes
    password_bytes = password.encode('utf-8')
    # Generar salt y hash
    salt = bcrypt.gensalt()
    password_hash = bcrypt.hashpw(password_bytes, salt)
    # Retornar como string
    return password_hash.decode('utf-8')

def verify_password(password: str, hashed_password: str) -> bool:
    """
    Verifica si una contraseña coincide con su hash
    """
    password_bytes = password.encode('utf-8')
    hashed_password_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_password_bytes)

def generate_random_password(length: int = 12) -> str:
    """
    Genera una contraseña aleatoria segura
    """
    # Caracteres seguros para contraseñas
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password

# Ejemplo de uso:
if __name__ == "__main__":
    # Crear hash de contraseña
    password = "mi_contraseña_segura"
    hashed = hash_password(password)
    print(f"Contraseña original: {password}")
    print(f"Hash: {hashed}")
    
    # Verificar contraseña
    is_valid = verify_password(password, hashed)
    print(f"¿Contraseña válida? {is_valid}")
    
    # Generar contraseña aleatoria
    random_pass = generate_random_password()
    print(f"Contraseña aleatoria: {random_pass}")
