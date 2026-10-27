import pytest

class FakeUploadedFile:
    def __init__(self, name: str, file_bytes: bytes) -> None:
        self.name = name
        self._file_bytes = file_bytes

    def getvalue(self) -> bytes:
        return self._file_bytes

class FakeSidebar:
    def __init__(self, parent: "FakeStreamlit") -> None:
        self.parent = parent

    def subheader(self, *args: object, **kwargs: object) -> None:
        self.parent.calls.append(("sidebar.subheader", args, kwargs))

    def write(self, *args: object, **kwargs: object) -> None:
        self.parent.calls.append(("sidebar.write", args, kwargs))

    def caption(self, *args: object, **kwargs: object) -> None:
        self.parent.calls.append(("sidebar.caption", args, kwargs))

    def code(self, *args: object, **kwargs: object) -> None:
        self.parent.calls.append(("sidebar.code", args, kwargs))

    def warning(self, *args: object, **kwargs: object) -> None:
        self.parent.calls.append(("sidebar.warning", args, kwargs))

class FakeStreamlit:
    def __init__(
        self,
        button_clicked: bool = False,
        uploaded_file: FakeUploadedFile | None = None,
        task_text: str = "",
        input_mode: str = "Single file",
        first_uploaded_file: FakeUploadedFile | None = None,
        second_uploaded_file: FakeUploadedFile | None = None,
        first_logical_name: str = "",
        second_logical_name: str = "",
        clicked_buttons: set[str] | None = None,
    ) -> None:
        self.session_state: dict[str, object] = {}
        self.calls: list[
            tuple[str, tuple[object, ...], dict[str, object]]
        ] = []
        self.button_clicked = button_clicked
        self.uploaded_file = uploaded_file
        self.task_text = task_text
        self.input_mode = input_mode
        self.first_uploaded_file = first_uploaded_file
        self.second_uploaded_file = second_uploaded_file
        self.first_logical_name = first_logical_name
        self.second_logical_name = second_logical_name
        self.clicked_buttons = clicked_buttons or set()
        self.sidebar = FakeSidebar(self)

    def title(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("title", args, kwargs))

    def write(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("write", args, kwargs))

    def file_uploader(
        self, *args: object, **kwargs: object
    ) -> FakeUploadedFile | None:
        self.calls.append(("file_uploader", args, kwargs))
        label = str(args[0]) if args else ""
        if "First" in label:
            return self.first_uploaded_file
        if "Second" in label:
            return self.second_uploaded_file
        return self.uploaded_file

    def radio(self, *args: object, **kwargs: object) -> str:
        self.calls.append(("radio", args, kwargs))
        return self.input_mode

    def text_input(self, *args: object, **kwargs: object) -> str:
        self.calls.append(("text_input", args, kwargs))
        label = str(args[0]) if args else ""
        if "First" in label:
            return self.first_logical_name
        if "Second" in label:
            return self.second_logical_name
        return str(kwargs.get("value", ""))

    def text_area(self, *args: object, **kwargs: object) -> str:
        self.calls.append(("text_area", args, kwargs))
        return self.task_text

    def button(self, *args: object, **kwargs: object) -> bool:
        self.calls.append(("button", args, kwargs))
        label = str(args[0]) if args else ""
        clicked = label in self.clicked_buttons or (
            self.button_clicked and label == "Generate"
        )
        return clicked and not bool(kwargs.get("disabled", False))

    def caption(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("caption", args, kwargs))

    def subheader(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("subheader", args, kwargs))

    def info(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("info", args, kwargs))

    def warning(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("warning", args, kwargs))

    def rerun(self) -> None:
        self.calls.append(("rerun", (), {}))

    def error(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("error", args, kwargs))

    def success(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("success", args, kwargs))

    def dataframe(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("dataframe", args, kwargs))

    def download_button(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("download_button", args, kwargs))

def install_streamlit(monkeypatch: pytest.MonkeyPatch, fake: FakeStreamlit) -> None:
    from snapscript.interfaces import web, web_assistant
    monkeypatch.setattr(web, "st", fake)
    monkeypatch.setattr(web_assistant, "st", fake)
