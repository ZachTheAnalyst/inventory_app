/*
 * Wires up .color-picker widgets: a button showing the current color, and a
 * dropdown list of swatches. Used instead of a native <select> because
 * browsers render an open <select>'s option list as an OS-level overlay --
 * the hover highlight on options in that overlay is drawn by the OS, not
 * CSS, so it can't reliably be changed (it just shows the system accent
 * color, blue on most setups). This is a fully custom, CSS-controlled
 * dropdown instead, so hovering an option can bold its text without any
 * blue highlight overriding its actual color.
 */
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.color-picker').forEach((picker) => {
        const trigger = picker.querySelector('.color-picker-trigger');
        const list = picker.querySelector('.color-picker-list');
        const hiddenInput = picker.querySelector('input[type="hidden"]');
        if (!trigger || !list || !hiddenInput) return;

        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.color-picker-list').forEach((otherList) => {
                if (otherList !== list) otherList.classList.add('hidden');
            });
            list.classList.toggle('hidden');
        });

        list.querySelectorAll('.color-picker-option').forEach((option) => {
            option.addEventListener('click', () => {
                const value = option.dataset.value;
                hiddenInput.value = value;
                trigger.textContent = value;
                trigger.style.background = option.style.background;
                trigger.style.color = option.style.color;
                list.classList.add('hidden');
            });
        });
    });

    // clicking anywhere outside a picker closes any open dropdown
    document.addEventListener('click', () => {
        document.querySelectorAll('.color-picker-list').forEach((l) => l.classList.add('hidden'));
    });
});
