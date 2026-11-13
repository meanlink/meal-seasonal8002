from sqlalchemy import String, JSON, Double, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    # 源数据更新后以新批次接入，并声明替代的旧批次；旧批次与旧试验结果永不改写。
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    created_at: Mapped[float] = mapped_column(Double)
