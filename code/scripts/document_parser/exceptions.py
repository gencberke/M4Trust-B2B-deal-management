"""Exception hierarchy for the runtime document parser."""


class DocumentParserError(Exception):
    """Base class for all errors raised by the document parser."""


class UnsupportedFileTypeError(DocumentParserError):
    """Raised when a file extension has no registered extractor."""


class ExtractionError(DocumentParserError):
    """Raised when an extractor fails to read a file it should support."""


class EmptyDocumentError(DocumentParserError):
    """Raised when extraction succeeds but produces no usable text."""
