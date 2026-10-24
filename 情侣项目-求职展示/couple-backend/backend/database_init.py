from backend.extensions import db
from backend.models import LoveGarden, User


DEFAULT_USERS = (
    ('girlfriend', '123456', '女朋友'),
    ('boyfriend', '123456', '男朋友'),
)


def initialize_database(app):
    with app.app_context():
        db.create_all()

        for username, password, role in DEFAULT_USERS:
            if User.query.filter_by(username=username).first():
                continue

            user = User(username=username, role=role)
            user.set_password(password)
            db.session.add(user)

        if not LoveGarden.query.first():
            db.session.add(LoveGarden())

        db.session.commit()
