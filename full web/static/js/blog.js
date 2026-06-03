// ============================================
// 1. Reading progress bar
// ============================================
window.addEventListener("scroll", () => {
  const winScroll = document.documentElement.scrollTop;
  const height = document.documentElement.scrollHeight - window.innerHeight;
  const scrolled = (winScroll / height) * 100;
  const progressBar = document.querySelector(".progress-bar");
  if (progressBar) {
    progressBar.style.width = scrolled + "%";
  }
});

// ============================================
// 2. Sticky Table of Contents (from h2, h3)
// ============================================
function generateTOC() {
  const headings = document.querySelectorAll(
    ".article-content h2, .article-content h3",
  );
  const tocList = document.querySelector(".toc ul");
  if (!headings.length || !tocList) return;

  // Clear existing TOC to avoid duplicates when re-running
  tocList.innerHTML = "";

  headings.forEach((h) => {
    if (!h.id) {
      h.id = h.innerText
        .toLowerCase()
        .replace(/\s+/g, "-")
        .replace(/[^\w-]/g, "");
    }
    const li = document.createElement("li");
    li.style.marginLeft = h.tagName === "H3" ? "1rem" : "0";
    li.innerHTML = `<a href="#${h.id}">${h.innerText}</a>`;
    tocList.appendChild(li);
  });
}

// ============================================
// 3. FAQ accordion (works for all .faq-question)
// ============================================
function initFaq() {
  document.querySelectorAll(".faq-question").forEach((btn) => {
    // Remove old listener to avoid duplicates (safe to call multiple times)
    btn.removeEventListener("click", btn._faqHandler);
    const handler = () => {
      const answer = btn.nextElementSibling;
      if (!answer) return;
      const isOpen = answer.style.maxHeight;
      answer.style.maxHeight = isOpen ? null : answer.scrollHeight + "px";
    };
    btn._faqHandler = handler;
    btn.addEventListener("click", handler);
  });
}

// ============================================
// 4. Back‑to‑top button (visibility + click)
// ============================================
const backBtn = document.querySelector(".back-to-top");
if (backBtn) {
  window.addEventListener("scroll", () => {
    backBtn.style.opacity = window.scrollY > 500 ? "1" : "0";
  });
  backBtn.addEventListener("click", (e) => {
    e.preventDefault();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

// ============================================
// 5. Share buttons (Twitter, Facebook, LinkedIn)
// ============================================
document.querySelectorAll(".share-btn").forEach((btn) => {
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    const url = encodeURIComponent(window.location.href);
    let shareUrl = "";
    if (btn.classList.contains("share-twitter"))
      shareUrl = `https://twitter.com/intent/tweet?url=${url}`;
    else if (btn.classList.contains("share-facebook"))
      shareUrl = `https://www.facebook.com/sharer/sharer.php?u=${url}`;
    else if (btn.classList.contains("share-linkedin"))
      shareUrl = `https://www.linkedin.com/shareArticle?mini=true&url=${url}`;
    if (shareUrl) window.open(shareUrl, "_blank", "width=600,height=400");
  });
});

// ============================================
// 6. Initialise everything when DOM is ready
// ============================================
document.addEventListener("DOMContentLoaded", () => {
  generateTOC();
  initFaq();
});
