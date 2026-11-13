from pydantic import BaseModel, Field
class DatasetInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=5, max_length=5000)
    # 源数据更新后重算：指向被替代的旧批次；旧批次及其试验结果保留不变。
    supersedes_id: int | None = Field(default=None)
