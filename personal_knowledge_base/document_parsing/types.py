from dataclasses import dataclass, field


@dataclass(slots=True)
class ParseWarning:
    code: str
    message: str
    block_index: int | None = None
    source_ref: str = ""

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "block_index": self.block_index,
            "source_ref": self.source_ref,
        }


@dataclass(slots=True)
class TextBlock:
    text: str
    block_index: int
    page_index: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class ImageBlock:
    data: bytes
    mime_type: str
    width: int
    height: int
    source_type: str
    source_ref: str
    block_index: int
    page_index: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDocument:
    text_blocks: list[TextBlock] = field(default_factory=list)
    images: list[ImageBlock] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)

    @property
    def ordered_blocks(self) -> list[TextBlock | ImageBlock]:
        return sorted([*self.text_blocks, *self.images], key=lambda item: item.block_index)
