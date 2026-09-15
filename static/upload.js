function initUploadWidget(inputId, thumbsId, addBtnId) {
  const input = document.getElementById(inputId);
  const thumbs = document.getElementById(thumbsId);
  const addBtn = document.getElementById(addBtnId);
  if (!input || !thumbs) return;

  let files = [];

  function fileLabel(name) {
    const label = document.createElement("span");
    label.className = "thumb-file";
    label.textContent = "📄 " + name;
    return label;
  }

  function render() {
    thumbs.innerHTML = "";
    files.forEach((file, idx) => {
      const item = document.createElement("div");
      item.className = "thumb";

      const isHeic = /\.(heic|heif)$/i.test(file.name);
      if (file.type.startsWith("image/") && !isHeic) {
        const img = document.createElement("img");
        img.src = URL.createObjectURL(file);
        // Most browsers (Safari being the exception) can't decode HEIC for
        // an <img>, even though they can upload the file fine - fall back
        // to the file-name label instead of a broken image icon.
        img.onerror = () => {
          img.replaceWith(fileLabel(file.name));
        };
        item.appendChild(img);
      } else {
        item.appendChild(fileLabel(file.name));
      }

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "thumb-remove";
      removeBtn.textContent = "×";
      removeBtn.addEventListener("click", () => {
        files.splice(idx, 1);
        sync();
      });
      item.appendChild(removeBtn);

      thumbs.appendChild(item);
    });
  }

  function sync() {
    const dt = new DataTransfer();
    files.forEach((f) => dt.items.add(f));
    input.files = dt.files;
    render();
  }

  input.addEventListener("change", () => {
    files = files.concat(Array.from(input.files));
    sync();
  });

  if (addBtn) {
    addBtn.addEventListener("click", () => input.click());
  }
}
