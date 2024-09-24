import logging
from datetime import datetime
from typing import Optional#, Union
#from typing_extensions import Annotated

from sqlalchemy import Integer, BigInteger, String, Text, ForeignKey, func, TypeDecorator, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, registry, validates
from sqlalchemy.ext.asyncio import AsyncAttrs

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.mysql import DATETIME

logger = logging.getLogger(__name__)

# default sqlalchemy does not have sub-second percision
# this allows up to a hundredth of a second
@compiles(DATETIME, "mysql")
def compile_datetime_mysql(type_, compiler, **kw):
     return "DATETIME(2)"

class String10(TypeDecorator):
    impl = String(10)
class String25(TypeDecorator):
    impl = String(25)
class String50(TypeDecorator):
    impl = String(50)
class String255(TypeDecorator):
    impl = String(255)

class Base(DeclarativeBase, AsyncAttrs):
    registry = registry(
        type_annotation_map={
            String10: String(10),
            String25: String(25),
            String50: String(50),
            String255: String(255)
        }
    )

class Users(Base):
    __tablename__ = 'Users'
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, unique=True)
    user_name: Mapped[String255]
    global_name: Mapped[Optional[String255]]
    display_name: Mapped[Optional[String255]]
    real_name: Mapped[Optional[String255]]
    timestamp_creation: Mapped[datetime] = mapped_column(default=func.now())
    logs: Mapped[list['UserLog']] = relationship(back_populates= 'user', lazy='selectin')
    info: Mapped['UserInfo'] = relationship(back_populates= 'user', lazy='joined')
    messages: Mapped[list['Messages']] = relationship(lazy='selectin', back_populates= 'user')
    messages_listened: Mapped[list['MessageListeners']] = relationship(back_populates= 'user', lazy='selectin')

class Bots(Base):
    __tablename__ = 'Bots'  # table name
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String255, nullable=False,unique=True)
    message_key: Mapped[str] = mapped_column(String10, nullable=False, unique=True)
    personality: Mapped[str]  = mapped_column(Text)
    desciption: Mapped[str] = mapped_column(Text) # Not used in the app, just for the web interface.
    voice: Mapped[str] = mapped_column(String50)
    speaker: Mapped[int]
    logs: Mapped[list['BotLog']] = relationship(back_populates= 'bot', lazy='selectin')
    knowledge: Mapped[list['Bot_kof_Users']] = relationship(backref='bot', lazy='selectin')
    bot_knowledge: Mapped[list['Bot_kof_Bots']] = relationship('Bot_kof_Bots', backref='bot', lazy='selectin', foreign_keys="[Bot_kof_Bots.bot_id]")
    messages: Mapped[list['Messages']] = relationship(back_populates='bot', lazy='selectin')
    messages_listened: Mapped[list['MessageListeners']] = relationship(back_populates='bot', lazy='selectin')

class Messages(Base):
    __tablename__ = 'Messages'  # table name
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey(Users.user_id), nullable=True)
    bot_id: Mapped[Bots] = mapped_column(Integer, ForeignKey(Bots.id), nullable=True)
    text: Mapped[Optional[str]] = mapped_column(Text)
    text_corrected: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_interrupted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DATETIME(2))
    tokens: Mapped[int]
    prompt_type: Mapped[str] = mapped_column(String10, nullable=False)
    discord_message_id: Mapped[BigInteger] = mapped_column
    listeners: Mapped[list['MessageListeners']] = relationship(lazy='selectin')
    user: Mapped[Users] = relationship()
    bot: Mapped[Bots] = relationship()

    @validates('user_id', 'bot_id')
    def validate_ids(self, key, value):
        if key == 'user_id' and self.bot_id is not None:
            raise ValueError("A message cannot have both a user_id and a bot_id")
        elif key == 'bot_id' and self.user_id is not None:
            raise ValueError("A message cannot have both a user_id and a bot_id")
        return value

class UserLog(Base):
    __tablename__ = 'UserLog'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey(Users.user_id))
    timestamp_in: Mapped[datetime]
    timestamp_out: Mapped[Optional[datetime]]
    user: Mapped[Users] = relationship(back_populates='logs', lazy='selectin')

class BotLog(Base):
    __tablename__ = 'BotLog'
    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, ForeignKey(Bots.id))
    timestamp_in: Mapped[datetime]
    timestamp_out: Mapped[Optional[datetime]]
    bot: Mapped[Bots] = relationship(back_populates='logs', lazy='selectin')

class UserInfo(Base):
    __tablename__ = 'UserInfo'
    id: Mapped[int] = mapped_column(primary_key= True)
    speech_corretions: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey(Users.user_id))
    user: Mapped[Users] = relationship(back_populates='info', lazy='joined')

class MessageListeners(Base):
    __tablename__ = 'MessageListeners'  # table name
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey(Users.user_id), nullable=True)
    bot_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey(Bots.id), nullable=True)
    message_id: Mapped[int] = mapped_column(ForeignKey(Messages.id))
    user: Mapped[Users] = relationship(back_populates='messages_listened', lazy='selectin')
    bot: Mapped[Bots] = relationship(back_populates='messages_listened', lazy='selectin')
    message: Mapped[Messages] = relationship(back_populates='listeners', lazy='selectin')

    @validates('user_id', 'bot_id')
    def validate_ids(self, key, value):
        if key == 'user_id' and self.bot_id is not None:
            raise ValueError("A message cannot have both a user_id and a bot_id")
        elif key == 'bot_id' and self.user_id is not None:
            raise ValueError("A message cannot have both a user_id and a bot_id")
        return value
    
class Bot_kof_Bots(Base):
    __tablename__ = 'BotKnowledgeofBots'  # table name
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey(Bots.id))
    other_bot_id: Mapped[int] = mapped_column(ForeignKey(Bots.id))
    knowledge: Mapped[str] = mapped_column(Text)
    opinion: Mapped[str] = mapped_column(Text)

class Bot_kof_Users(Base):
    __tablename__ = 'BotKnowledgeofUsers'  # table name
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey(Bots.id))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey(Users.user_id))
    knowledge: Mapped[str] = mapped_column(Text)
    opinion: Mapped[str] = mapped_column(Text)
    #bot: Mapped['Bots'] = relationship()
    #user: Mapped['Users'] = relationship()    