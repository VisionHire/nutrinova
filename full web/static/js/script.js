// =====================
// 🌿 NAV MENU TOGGLE (Mobile)
// =====================
const toggle = document.getElementById("menu-toggle");
const links = document.getElementById("nav-links");

if (toggle && links) {
  toggle.addEventListener("click", () => {
    links.classList.toggle("show");
  });
}

// =====================
// 🔽 CLICKABLE DROPDOWN (Features)
// =====================
const dropdown = document.getElementById("features-dropdown");
if (dropdown) {
  const dropdownToggle = dropdown.querySelector(".dropdown-toggle");
  const dropdownMenu = dropdown.querySelector(".dropdown-menu");

  if (dropdownToggle && dropdownMenu) {
    dropdownToggle.addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown.classList.toggle("open");
      dropdownMenu.classList.toggle("show");
    });

    // Close dropdown when clicking outside
    window.addEventListener("click", (e) => {
      if (!dropdown.contains(e.target)) {
        dropdown.classList.remove("open");
        dropdownMenu.classList.remove("show");
      }
    });
  }
}

// =====================
// 🍎 FOODS.JSON FETCH (optional logging)
// =====================
async function loadFoodData() {
  try {
    const response = await fetch(
      typeof FOODS_JSON_URL !== "undefined" ? FOODS_JSON_URL : "/static/data/foods.json"
    );
    if (!response.ok) throw new Error("Failed to fetch foods.json");

    const foods = await response.json();
    console.log(`✅ Loaded ${Object.keys(foods).length} food items`);
  } catch (error) {
    console.error("❌ Error loading foods.json:", error);
  }
}

window.addEventListener("DOMContentLoaded", loadFoodData);

// =====================
// 🎨 OPTIONAL: Animate Dropdown Arrow Rotation
// =====================
document.querySelectorAll(".dropdown-toggle").forEach((toggle) => {
  toggle.addEventListener("click", () => {
    toggle.classList.toggle("active");
  });
});
