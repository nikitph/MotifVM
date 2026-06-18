def is_admin(user):
    return bool(user and user.role == "admin")
