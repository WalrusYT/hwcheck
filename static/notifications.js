function initNotifDropdown(bellId, dropdownId) {
  const bell = document.getElementById(bellId);
  const dropdown = document.getElementById(dropdownId);
  if (!bell || !dropdown) return;

  bell.addEventListener("click", (e) => {
    e.stopPropagation();
    dropdown.hidden = !dropdown.hidden;
  });

  document.addEventListener("click", (e) => {
    if (!dropdown.hidden && !dropdown.contains(e.target) && e.target !== bell) {
      dropdown.hidden = true;
    }
  });
}
