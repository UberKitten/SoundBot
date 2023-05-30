function copyToClipboard(text) {
  if (!navigator.clipboard) {
    return new Promise((resolve, reject) => {
      const selection = document.getSelection();
      const range = document.createRange();
      const textEl = document.createElement("span");

      textEl.innerText = text;
      textEl.style.opacity = 0;
      document.body.appendChild(textEl);

      selection.removeAllRanges();
      range.selectNode(textEl);
      selection.addRange(range);

      const result = document.execCommand("copy");
      selection.removeAllRanges();
      document.body.removeChild(textEl);

      result
        ? resolve(result)
        : reject(new Error("Copy command is unsupported or disabled"));
    });
  }

  return navigator.clipboard.writeText(text);
}

function copy(eTarget, _displayTarget) {
  const displayTarget = _displayTarget ?? eTarget;
  const data = eTarget.dataset;
  const prevContent = displayTarget.innerHTML;
  let text = data.copyText || "";

  copyToClipboard(text)
    .then(() => (displayTarget.innerText = "COPIED!"))
    .catch((e) => {
      console.error(e);
      displayTarget.innerText = "Error Copying ☹";
    })
    .finally(() =>
      setTimeout(() => {
        displayTarget.innerHTML = prevContent;
      }, 1800)
    );
}
