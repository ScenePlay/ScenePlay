"""bcrypt helpers with the Flask-Bcrypt call shape (12 rounds, $2b$ prefix,
no pre-hash) so existing tblUsers hashes — and the relay portal, which logs
players in against the same hashes — keep verifying."""
import bcrypt as _bcrypt


class _Bcrypt:
    rounds = 12

    def generate_password_hash(self, password, rounds=None):
        if isinstance(password, str):
            password = password.encode('utf-8')
        return _bcrypt.hashpw(password, _bcrypt.gensalt(rounds or self.rounds))

    def check_password_hash(self, pw_hash, password):
        if isinstance(pw_hash, str):
            pw_hash = pw_hash.encode('utf-8')
        if isinstance(password, str):
            password = password.encode('utf-8')
        try:
            return _bcrypt.checkpw(password, pw_hash)
        except (ValueError, TypeError):
            return False


bcrypt = _Bcrypt()
