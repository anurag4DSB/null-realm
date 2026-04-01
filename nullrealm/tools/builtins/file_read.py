"""File read tool for Null Realm agents."""

from nullrealm.tools.base import BaseTool


class FileReadTool(BaseTool):
    name = "file_read"
    description = "Read the contents of a file given its path"

    async def execute(self, path: str) -> str:
        try:
            with open(path) as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"
