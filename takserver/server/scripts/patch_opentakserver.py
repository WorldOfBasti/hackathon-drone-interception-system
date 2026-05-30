#!/usr/bin/env python3
"""Apply Docker runtime patches to the installed OpenTAKServer package."""

from __future__ import annotations

import sysconfig
from pathlib import Path


PACKAGE_DIR = Path(sysconfig.get_paths()["purelib"]) / "opentakserver"

HELPER = '''

def _rabbitmq_socketio_url(app):
    from urllib.parse import quote

    username = quote(str(app.config.get("OTS_RABBITMQ_USERNAME")), safe="")
    password = quote(str(app.config.get("OTS_RABBITMQ_PASSWORD")), safe="")
    host = app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")
    return f"amqp://{username}:{password}@{host}"
'''


def patch_socketio_file(path: Path) -> None:
    text = path.read_text()

    if "def _rabbitmq_socketio_url(app):" not in text:
        marker = "\n\ndef get_locale():"
        if marker in text:
            text = text.replace(marker, HELPER + marker, 1)
        else:
            marker = "\n\nclass CoTController:"
            text = text.replace(marker, HELPER + marker, 1)

    text = text.replace(
        'message_queue="amqp://" + app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")',
        "message_queue=_rabbitmq_socketio_url(app)",
    )
    text = text.replace(
        "and not self.rabbit_channel.is_closing",
        'and not getattr(self.rabbit_channel, "is_closing", False)',
    )
    path.write_text(text)


def patch_eud_handler(path: Path) -> None:
    text = path.read_text()
    text = text.replace(
        "and not self.rabbit_channel.is_closing",
        'and not getattr(self.rabbit_channel, "is_closing", False)',
    )

    guard = '''        if not self.rabbit_channel or not self.rabbit_channel.is_open:
            if not self.shutdown:
                self.shutdown = True
                try:
                    self.request.shutdown(SHUT_RDWR)
                except OSError:
                    pass
                self.request.close()
            return

'''
    marker = (
        '        self.logger.info("{} disconnected".format(self.client_address[0]))\n\n'
        "        self.rabbit_channel.basic_publish(\n"
    )
    if guard not in text:
        text = text.replace(
            marker,
            '        self.logger.info("{} disconnected".format(self.client_address[0]))\n\n'
            + guard
            + "        self.rabbit_channel.basic_publish(\n",
            1,
        )

    callsign_marker = '''            if "callsign" in contact.attrs:
                self.callsign = contact.attrs["callsign"]

                # Declare a RabbitMQ Queue for this uid and join the 'dms' and 'cot' exchanges
'''
    callsign_patch = '''            if "callsign" in contact.attrs:
                raw_callsign = bleach.clean(contact.attrs.get("callsign") or "").strip()
                if not raw_callsign and self.user:
                    raw_callsign = self.user.username.title()
                if self.is_ssl and self.user and raw_callsign.casefold() in {"iphone", "ipad", "android", "atak", "itak"}:
                    raw_callsign = self.user.username.title()
                self.callsign = raw_callsign or uid

                if self.is_ssl and self.user:
                    with self.app.app_context():
                        conflict = db.session.execute(
                            select(EUD).where(EUD.callsign == self.callsign, EUD.uid != uid)
                        ).first()
                        if conflict:
                            base_callsign = self.user.username.title()
                            self.callsign = base_callsign
                            if db.session.execute(
                                select(EUD).where(EUD.callsign == self.callsign, EUD.uid != uid)
                            ).first():
                                self.callsign = f"{base_callsign}-{uid[-4:]}"
                            self.logger.warning(
                                f"Changed duplicate callsign {raw_callsign!r} to {self.callsign!r} for {uid}"
                            )

                # Declare a RabbitMQ Queue for this uid and join the 'dms' and 'cot' exchanges
'''
    if callsign_patch not in text:
        text = text.replace(callsign_marker, callsign_patch, 1)

    text = text.replace(
        '''                if not raw_callsign and self.user:
                    raw_callsign = self.user.username.title()
                self.callsign = raw_callsign or uid
''',
        '''                if not raw_callsign and self.user:
                    raw_callsign = self.user.username.title()
                if self.is_ssl and self.user and raw_callsign.casefold() in {"iphone", "ipad", "android", "atak", "itak"}:
                    raw_callsign = self.user.username.title()
                self.callsign = raw_callsign or uid
''',
        1,
    )

    insert_marker = '''                try:
                    db.session.add(eud)
                    db.session.commit()
                except sqlalchemy.exc.IntegrityError:
                    db.session.rollback()
                    db.session.execute(
                        update(EUD).where(EUD.uid == eud.uid).values(**eud.serialize())
                    )
                    db.session.commit()
'''
    insert_patch = '''                try:
                    db.session.add(eud)
                    db.session.commit()
                except sqlalchemy.exc.IntegrityError:
                    db.session.rollback()
                    existing = db.session.execute(select(EUD).filter_by(uid=eud.uid)).first()
                    if existing:
                        db.session.execute(
                            update(EUD).where(EUD.uid == eud.uid).values(**eud.serialize())
                        )
                    else:
                        if eud.callsign and db.session.execute(
                            select(EUD).where(EUD.callsign == eud.callsign)
                        ).first():
                            base_callsign = self.user.username.title() if self.user else eud.uid[-8:]
                            eud.callsign = base_callsign
                            if db.session.execute(select(EUD).where(EUD.callsign == eud.callsign)).first():
                                eud.callsign = f"{base_callsign}-{eud.uid[-4:]}"
                            self.callsign = eud.callsign
                        db.session.add(eud)
                    db.session.commit()
'''
    if insert_patch not in text:
        text = text.replace(insert_marker, insert_patch, 1)

    path.write_text(text)


def patch_eud_model(path: Path) -> None:
    text = path.read_text()

    if "def _latest_valid_point_for_eud" not in text:
        marker = "\n@dataclass\nclass EUD(db.Model):"
        helper = '''

def _latest_valid_point_for_eud(uid):
    from opentakserver.models.Point import Point

    return (
        db.session.query(Point)
        .filter(Point.device_uid == uid)
        .filter(Point.latitude >= -90)
        .filter(Point.latitude <= 90)
        .filter(Point.longitude >= -180)
        .filter(Point.longitude <= 180)
        .order_by(Point.timestamp.desc(), Point.id.desc())
        .first()
    )
'''
        text = text.replace(marker, helper + marker, 1)

    text = text.replace(
        '            "last_point": None,  # Setting to None for now since it can cause a huge overhead when an EUD has lots of points in the DB',
        '            "last_point": last_point.to_json() if (last_point := _latest_valid_point_for_eud(self.uid)) else None,',
    )

    path.write_text(text)


def main() -> None:
    patch_socketio_file(PACKAGE_DIR / "app.py")
    patch_socketio_file(PACKAGE_DIR / "cot_parser" / "cot_parser.py")
    patch_eud_handler(PACKAGE_DIR / "eud_handler" / "EudHandler.py")
    patch_eud_model(PACKAGE_DIR / "models" / "EUD.py")


if __name__ == "__main__":
    main()
