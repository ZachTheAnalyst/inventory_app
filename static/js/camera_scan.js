/*
 * Wires a "Scan with camera" button to an Html5Qrcode reader. Used on any
 * page with a barcode scan-input, as an alternative to a physical USB/BT
 * scanner (which just types into the field and sends Enter).
 */
function initCameraScan(buttonId, containerId, onDecoded) {
    const button = document.getElementById(buttonId);
    const container = document.getElementById(containerId);
    if (!button || !container) return;

    let scanner = null;
    let active = false;

    async function stopScanner() {
        if (scanner) {
            try {
                await scanner.stop();
                scanner.clear();
            } catch (err) {
                // already stopped
            }
            scanner = null;
        }
        container.classList.add('hidden');
        button.textContent = '📷 Scan with camera';
        active = false;
    }

    button.addEventListener('click', async () => {
        if (active) {
            await stopScanner();
            return;
        }

        if (!window.isSecureContext) {
            alert('Camera scanning needs HTTPS (or localhost). Ask for the https:// link to this app.');
            return;
        }
        if (typeof Html5Qrcode === 'undefined') {
            alert('Camera scanning library failed to load.');
            return;
        }

        container.classList.remove('hidden');
        button.textContent = 'Stop camera';
        active = true;
        scanner = new Html5Qrcode(containerId, {
            formatsToSupport: [Html5QrcodeSupportedFormats.CODE_128],
            // Uses the browser's native, hardware-accelerated BarcodeDetector
            // API when available (Chrome/Edge/Android) instead of the much
            // slower pure-JS decode loop. Silently no-ops (falls back to the
            // JS decoder) on browsers without it, e.g. iOS Safari.
            experimentalFeatures: { useBarCodeDetectorIfSupported: true },
            verbose: false,
        });

        try {
            await scanner.start(
                { facingMode: 'environment' },
                {
                    fps: 15,
                    // Code128 is a wide, short 1D barcode -- a box shaped to
                    // match it (wide/short, not square) means less area to
                    // scan per frame and an easier real-world alignment.
                    qrbox: { width: 280, height: 100 },
                    aspectRatio: 1.7777778,
                    disableFlip: true,
                    videoConstraints: {
                        facingMode: 'environment',
                        width: { ideal: 1280 },
                        height: { ideal: 720 },
                    },
                },
                async (decodedText) => {
                    await stopScanner();
                    onDecoded(decodedText.trim().toUpperCase());
                },
                () => {} // per-frame "no barcode found" callback -- ignored
            );
        } catch (err) {
            console.error('Camera scan failed to start', err);
            alert('Could not access the camera: ' + err);
            await stopScanner();
        }
    });
}
