/*
 * Mobile nav: hamburger button opens a slide-out drawer from the left.
 * Closes on the X button, clicking the overlay outside the panel, or
 * clicking any link inside it. Desktop nav (.nav-links) is untouched --
 * this only wires up elements that exist when the mobile drawer is
 * present at all (logged-in pages; see base.html).
 */
document.addEventListener('DOMContentLoaded', () => {
    const hamburgerBtn = document.getElementById('hamburger-btn');
    const drawer = document.getElementById('nav-drawer');
    const overlay = document.getElementById('nav-overlay');
    const closeBtn = document.getElementById('nav-drawer-close');
    if (!hamburgerBtn || !drawer || !overlay) return;

    function openDrawer() {
        drawer.classList.add('open');
        overlay.classList.add('open');
        drawer.setAttribute('aria-hidden', 'false');
        hamburgerBtn.setAttribute('aria-expanded', 'true');
    }

    function closeDrawer() {
        drawer.classList.remove('open');
        overlay.classList.remove('open');
        drawer.setAttribute('aria-hidden', 'true');
        hamburgerBtn.setAttribute('aria-expanded', 'false');
    }

    hamburgerBtn.addEventListener('click', openDrawer);
    closeBtn.addEventListener('click', closeDrawer);
    overlay.addEventListener('click', closeDrawer);
    drawer.querySelectorAll('a').forEach((link) => {
        link.addEventListener('click', closeDrawer);
    });
});
