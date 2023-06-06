export function copyToClipboard(text: string) {
  if (!navigator.clipboard) {
    return new Promise((resolve, reject) => {
      const selection = document.getSelection();

      if (!selection) {
        reject(new Error("Text selection API is unavailable"));
        return;
      }

      const range = document.createRange();
      const textEl = document.createElement("span");

      textEl.innerText = text;
      textEl.style.opacity = "0";
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

export function copy(
  eTarget: EventTarget,
  _displayTarget?: HTMLElement | null
) {
  if (!(eTarget instanceof HTMLElement)) {
    console.error(new Error("Copy target is not an HTML element"));
    return;
  }

  const displayTarget = _displayTarget ?? eTarget;
  const contentMutable =
    (parseInt(eTarget.dataset.currentCopyOps ?? "0", 10) || 0) === 0;
  const prevContent = contentMutable && displayTarget.innerHTML;
  let text = eTarget.dataset.copyText || "";

  eTarget.dataset.currentCopyOps = (
    (parseInt(eTarget.dataset.currentCopyOps ?? "0", 10) || 0) + 1
  ).toString();

  copyToClipboard(text)
    .then(() => contentMutable && (displayTarget.innerText = "COPIED!"))
    .catch((e) => {
      console.error(e);
      contentMutable && (displayTarget.innerText = "Error Copying ☹");
    })
    .finally(() =>
      setTimeout(() => {
        prevContent !== false && (displayTarget.innerHTML = prevContent);
        eTarget.dataset.currentCopyOps = (
          (parseInt(eTarget.dataset.currentCopyOps ?? "0", 10) || 0) - 1
        ).toString();
      }, 500)
    );
}
