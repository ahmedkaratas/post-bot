// InstaFit 1080x1350 - Core Canvas Application
(() => {
  const CANVAS_WIDTH = 1080;
  const CANVAS_HEIGHT = 1350;
  const SNAP_THRESHOLD = 12; // Canvas pikseli cinsinden manyetik yapışma mesafesi

  // DOM Elemanları
  const canvas = document.getElementById('preview-canvas');
  const ctx = canvas.getContext('2d');
  const canvasWrapper = document.getElementById('canvas-wrapper');
  const emptyState = document.getElementById('empty-state');
  const fileInput = document.getElementById('file-input');

  const guideV = document.getElementById('guide-v');
  const guideH = document.getElementById('guide-h');

  // Kontrol Butonları & Slider'lar
  const btnDownload = document.getElementById('btn-download');
  const btnShare = document.getElementById('btn-share');
  const btnAutoFit = document.getElementById('btn-autofit');
  const btnCenter = document.getElementById('btn-center');
  const btnFitWidth = document.getElementById('btn-fit-width');
  const btnFitHeight = document.getElementById('btn-fit-height');

  const zoomSlider = document.getElementById('zoom-slider');
  const zoomValueText = document.getElementById('zoom-value');
  const btnZoomIn = document.getElementById('btn-zoom-in');
  const btnZoomOut = document.getElementById('btn-zoom-out');

  const radiusSlider = document.getElementById('radius-slider');
  const radiusValText = document.getElementById('radius-val');
  const toggleBorder = document.getElementById('toggle-border');

  // Netlik (Sharpen) Elemanları
  const btnToggleSharpen = document.getElementById('btn-toggle-sharpen');
  const sharpenSlider = document.getElementById('sharpen-slider');
  const sharpenValText = document.getElementById('sharpen-val');
  const btnAiUpscale = document.getElementById('btn-ai-upscale');

  // AI Modal Elemanları
  const aiModal = document.getElementById('ai-modal');
  const aiModalTitle = document.getElementById('ai-modal-title');
  const aiModalDesc = document.getElementById('ai-modal-desc');
  const aiProgressFill = document.getElementById('ai-progress-fill');
  const aiProgressText = document.getElementById('ai-progress-text');

  // Uygulama Durumu (State)
  let rawImage = null;      // Orijinal yüklenen görsel
  let currentImage = null;  // Ekranda çizilen (gerekirse netleştirilmiş) görsel
  let posX = CANVAS_WIDTH / 2;
  let posY = CANVAS_HEIGHT / 2;
  let scale = 1.0;
  let baseFitScale = 1.0;
  let borderRadius = 0;
  let showBorder = false;
  let sharpenPercent = 0;
  let sharpenTimeout = null;
  let upscalerInstance = null;
  let isUpscaling = false;

  // Etkileşim Durumu (Pointer / Touch)
  let isDragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let imgStartX = 0;
  let imgStartY = 0;

  // Çoklu dokunma (Pinch-to-zoom)
  let initialPinchDistance = null;
  let initialScaleOnPinch = 1.0;

  // 1. Görsel Yükleme Fonksiyonu
  function loadImage(fileOrBlob) {
    if (!fileOrBlob || !fileOrBlob.type.startsWith('image/')) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        rawImage = img;
        emptyState.style.display = 'none';

        if (sharpenPercent > 0) {
          currentImage = applySmartSharpen(rawImage, sharpenPercent / 100);
        } else {
          currentImage = rawImage;
        }

        // Otomatik sığdır ve tam ortaya yerleştir
        autoFitImage();
        render();
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(fileOrBlob);
  }

  // Akıllı ve Doğal Netleştirme (Unsharp Masking - Yapay Olmayan Netlik)
  // Ekran görüntüsü yazılarını, kenarları ve fotoğrafları yapaylaştırmadan/karikatürize etmeden jilet gibi yapar.
  function applySmartSharpen(sourceImg, amount) {
    if (!sourceImg || amount <= 0) return sourceImg;

    const w = sourceImg.width;
    const h = sourceImg.height;

    const baseCanvas = document.createElement('canvas');
    baseCanvas.width = w;
    baseCanvas.height = h;
    const baseCtx = baseCanvas.getContext('2d');
    baseCtx.drawImage(sourceImg, 0, 0);

    const imgData = baseCtx.getImageData(0, 0, w, h);
    const data = imgData.data;

    // Donanım hızlandırmalı hafif bulanık katman (Kenar frekans farkını yakalamak için)
    const blurCanvas = document.createElement('canvas');
    blurCanvas.width = w;
    blurCanvas.height = h;
    const blurCtx = blurCanvas.getContext('2d');
    blurCtx.filter = 'blur(1.2px)';
    blurCtx.drawImage(sourceImg, 0, 0);
    const blurData = blurCtx.getImageData(0, 0, w, h).data;

    // Eşikli Yüksek Frekans Vurgulama (Düz alanlarda parazit yapmaz, harf ve kenarları netleştirir)
    const threshold = 3;
    const factor = amount * 1.5;
    const len = data.length;

    for (let i = 0; i < len; i += 4) {
      const diffR = data[i] - blurData[i];
      const diffG = data[i + 1] - blurData[i + 1];
      const diffB = data[i + 2] - blurData[i + 2];

      if (Math.abs(diffR) > threshold) {
        data[i] = Math.min(255, Math.max(0, data[i] + diffR * factor));
      }
      if (Math.abs(diffG) > threshold) {
        data[i + 1] = Math.min(255, Math.max(0, data[i + 1] + diffG * factor));
      }
      if (Math.abs(diffB) > threshold) {
        data[i + 2] = Math.min(255, Math.max(0, data[i + 2] + diffB * factor));
      }
    }

    baseCtx.putImageData(imgData, 0, 0);
    return baseCanvas;
  }

  function updateSharpen(percent) {
    sharpenPercent = percent;
    sharpenSlider.value = percent;
    sharpenValText.textContent = `${percent}%`;

    if (btnToggleSharpen) {
      btnToggleSharpen.classList.toggle('active', percent > 0);
    }

    if (!rawImage) return;

    if (percent === 0) {
      currentImage = rawImage;
      render();
    } else {
      clearTimeout(sharpenTimeout);
      sharpenTimeout = setTimeout(() => {
        currentImage = applySmartSharpen(rawImage, percent / 100);
        render();
      }, 30);
    }
  }

  // 2. Otomatik Sığdırma (Auto-Fit) Mantığı
  // Kullanıcının isteği: Yatay ise yanlara değsin, dikey ise üst ve alta değsin (en-boy oranını bozmadan)
  function autoFitImage() {
    if (!currentImage) return;

    const imgAspect = currentImage.width / currentImage.height;
    const canvasAspect = CANVAS_WIDTH / CANVAS_HEIGHT; // 1080 / 1350 = 0.8

    // Sığdırma katsayısı: Taşırmadan tam sığacak en büyük ölçek
    if (imgAspect > canvasAspect) {
      // Görsel daha yatay -> genişlik tam 1080px'e sığdırılır
      scale = CANVAS_WIDTH / currentImage.width;
    } else {
      // Görsel daha dikey -> yükseklik tam 1350px'e sığdırılır
      scale = CANVAS_HEIGHT / currentImage.height;
    }

    baseFitScale = scale;
    posX = CANVAS_WIDTH / 2;
    posY = CANVAS_HEIGHT / 2;

    updateZoomUI();
    render();
  }

  function fitToWidth() {
    if (!currentImage) return;
    scale = CANVAS_WIDTH / currentImage.width;
    posX = CANVAS_WIDTH / 2;
    updateZoomUI();
    render();
  }

  function fitToHeight() {
    if (!currentImage) return;
    scale = CANVAS_HEIGHT / currentImage.height;
    posY = CANVAS_HEIGHT / 2;
    updateZoomUI();
    render();
  }

  function centerImage() {
    if (!currentImage) return;
    posX = CANVAS_WIDTH / 2;
    posY = CANVAS_HEIGHT / 2;
    render();
    flashGuides();
  }

  function updateZoomUI() {
    if (!baseFitScale) return;
    const percent = Math.round((scale / baseFitScale) * 100);
    zoomSlider.value = percent;
    zoomValueText.textContent = `${percent}%`;
  }

  function setZoomFromPercent(percent) {
    if (!currentImage || !baseFitScale) return;
    scale = (percent / 100) * baseFitScale;
    zoomSlider.value = percent;
    zoomValueText.textContent = `${percent}%`;
    render();
  }

  function flashGuides() {
    guideV.classList.add('active');
    guideH.classList.add('active');
    setTimeout(() => {
      guideV.classList.remove('active');
      guideH.classList.remove('active');
    }, 400);
  }

  // 3. Çizim / Render (60 FPS Doğal Canvas)
  function render() {
    // 1080x1350 Siyah Arka Plan
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

    if (!currentImage) return;

    const drawW = currentImage.width * scale;
    const drawH = currentImage.height * scale;
    const drawX = posX - drawW / 2;
    const drawY = posY - drawH / 2;

    ctx.save();

    // Köşe Yuvarlama (Path Clip)
    if (borderRadius > 0) {
      const r = Math.min(borderRadius, drawW / 2, drawH / 2);
      ctx.beginPath();
      ctx.moveTo(drawX + r, drawY);
      ctx.arcTo(drawX + drawW, drawY, drawX + drawW, drawY + drawH, r);
      ctx.arcTo(drawX + drawW, drawY + drawH, drawX, drawY + drawH, r);
      ctx.arcTo(drawX, drawY + drawH, drawX, drawY, r);
      ctx.arcTo(drawX, drawY, drawX + drawW, drawY, r);
      ctx.closePath();
      ctx.clip();
    }

    // Görseli Çiz
    ctx.drawImage(currentImage, drawX, drawY, drawW, drawH);

    // İnce Kenarlık (Opsiyonel)
    if (showBorder) {
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    ctx.restore();
  }

  // 4. Manyetik Hizalama Kılavuzları
  function checkSnapGuides() {
    const isSnapV = Math.abs(posX - CANVAS_WIDTH / 2) < SNAP_THRESHOLD;
    const isSnapH = Math.abs(posY - CANVAS_HEIGHT / 2) < SNAP_THRESHOLD;

    if (isSnapV) {
      posX = CANVAS_WIDTH / 2;
      guideV.classList.add('active');
    } else {
      guideV.classList.remove('active');
    }

    if (isSnapH) {
      posY = CANVAS_HEIGHT / 2;
      guideH.classList.add('active');
    } else {
      guideH.classList.remove('active');
    }
  }

  function hideGuides() {
    guideV.classList.remove('active');
    guideH.classList.remove('active');
  }

  // 5. Fare & Dokunmatik Kontroller
  function getCanvasCoord(clientX, clientY) {
    const rect = canvasWrapper.getBoundingClientRect();
    const factorX = CANVAS_WIDTH / rect.width;
    const factorY = CANVAS_HEIGHT / rect.height;
    return {
      x: (clientX - rect.left) * factorX,
      y: (clientY - rect.top) * factorY
    };
  }

  // Fare Olayları
  canvasWrapper.addEventListener('mousedown', (e) => {
    if (!currentImage) return;
    isDragging = true;
    const pos = getCanvasCoord(e.clientX, e.clientY);
    dragStartX = pos.x;
    dragStartY = pos.y;
    imgStartX = posX;
    imgStartY = posY;
  });

  window.addEventListener('mousemove', (e) => {
    if (!isDragging || !currentImage) return;
    const pos = getCanvasCoord(e.clientX, e.clientY);
    posX = imgStartX + (pos.x - dragStartX);
    posY = imgStartY + (pos.y - dragStartY);

    checkSnapGuides();
    render();
  });

  window.addEventListener('mouseup', () => {
    if (isDragging) {
      isDragging = false;
      hideGuides();
    }
  });

  // Fare Tekerleği ile Zoom
  canvasWrapper.addEventListener('wheel', (e) => {
    if (!currentImage) return;
    e.preventDefault();

    const zoomStep = e.deltaY < 0 ? 1.05 : 0.95;
    scale = Math.max(0.05, Math.min(10, scale * zoomStep));
    updateZoomUI();
    render();
  }, { passive: false });

  // Dokunmatik Olaylar (Mobil iPhone/iPad)
  canvasWrapper.addEventListener('touchstart', (e) => {
    if (!currentImage) return;

    if (e.touches.length === 1) {
      isDragging = true;
      const t = e.touches[0];
      const pos = getCanvasCoord(t.clientX, t.clientY);
      dragStartX = pos.x;
      dragStartY = pos.y;
      imgStartX = posX;
      imgStartY = posY;
    } else if (e.touches.length === 2) {
      // İki parmakla kıstırma (Pinch-to-zoom)
      isDragging = false;
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      initialPinchDistance = Math.hypot(dx, dy);
      initialScaleOnPinch = scale;
    }
  }, { passive: true });

  canvasWrapper.addEventListener('touchmove', (e) => {
    if (!currentImage) return;

    if (e.touches.length === 1 && isDragging) {
      const t = e.touches[0];
      const pos = getCanvasCoord(t.clientX, t.clientY);
      posX = imgStartX + (pos.x - dragStartX);
      posY = imgStartY + (pos.y - dragStartY);

      checkSnapGuides();
      render();
    } else if (e.touches.length === 2 && initialPinchDistance) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const currentDist = Math.hypot(dx, dy);
      const ratio = currentDist / initialPinchDistance;

      scale = Math.max(0.05, Math.min(10, initialScaleOnPinch * ratio));
      updateZoomUI();
      render();
    }
  }, { passive: true });

  canvasWrapper.addEventListener('touchend', (e) => {
    if (e.touches.length === 0) {
      isDragging = false;
      initialPinchDistance = null;
      hideGuides();
    }
  });

  // 6. Dosya Seçimi & Drag-and-Drop & Panodan Yapıştırma
  fileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      loadImage(e.target.files[0]);
    }
  });

  emptyState.addEventListener('click', () => {
    fileInput.click();
  });

  // Sürükle Bırak (Drag & Drop)
  window.addEventListener('dragover', (e) => {
    e.preventDefault();
    emptyState.classList.add('drag-over');
  });

  window.addEventListener('dragleave', (e) => {
    if (e.clientX <= 0 || e.clientY <= 0) {
      emptyState.classList.remove('drag-over');
    }
  });

  window.addEventListener('drop', (e) => {
    e.preventDefault();
    emptyState.classList.remove('drag-over');
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      loadImage(e.dataTransfer.files[0]);
    }
  });

  // Panodan Yapıştırma (Cmd+V / Ctrl+V)
  window.addEventListener('paste', (e) => {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;
    for (let item of items) {
      if (item.type.indexOf('image') !== -1) {
        const blob = item.getAsFile();
        loadImage(blob);
        break;
      }
    }
  });

  // 7. Kontrol Paneli Olayları
  btnAutoFit.addEventListener('click', autoFitImage);
  btnCenter.addEventListener('click', centerImage);
  btnFitWidth.addEventListener('click', fitToWidth);
  btnFitHeight.addEventListener('click', fitToHeight);

  zoomSlider.addEventListener('input', (e) => {
    setZoomFromPercent(parseInt(e.target.value, 10));
  });

  btnZoomIn.addEventListener('click', () => {
    const current = parseInt(zoomSlider.value, 10);
    setZoomFromPercent(Math.min(300, current + 5));
  });

  btnZoomOut.addEventListener('click', () => {
    const current = parseInt(zoomSlider.value, 10);
    setZoomFromPercent(Math.max(10, current - 5));
  });

  radiusSlider.addEventListener('input', (e) => {
    borderRadius = parseInt(e.target.value, 10);
    radiusValText.textContent = `${borderRadius}px`;
    render();
  });

  toggleBorder.addEventListener('change', (e) => {
    showBorder = e.target.checked;
    render();
  });

  // Netlik Olayları
  sharpenSlider.addEventListener('input', (e) => {
    updateSharpen(parseInt(e.target.value, 10));
  });

  btnToggleSharpen.addEventListener('click', () => {
    // Tek tıkla %40 Doğal Netlik aç / kapat
    if (sharpenPercent === 0) {
      updateSharpen(40);
    } else {
      updateSharpen(0);
    }
  });

  // 7.5. Gerçek Yapay Zeka ile Süper Çözünürlük (2x AI Upscale - ESRGAN)
  // 720p bir görseli gerçek pikseller üreterek 1080p/2K çözünürlüğe yükseltir.
  async function upscaleWithAI() {
    if (!rawImage) {
      alert('Lütfen önce bir ekran görüntüsü yükleyin.');
      return;
    }

    if (isUpscaling) return;
    isUpscaling = true;

    // Modalı aç
    aiModal.classList.add('active');
    aiProgressFill.style.width = '15%';
    aiProgressText.textContent = '15%';
    aiModalTitle.textContent = 'AI Modeli Hazırlanıyor...';
    aiModalDesc.textContent = 'Derin öğrenme ağı WebGL donanımında başlatılıyor...';

    try {
      if (typeof Upscaler !== 'undefined') {
        if (!upscalerInstance) {
          upscalerInstance = new Upscaler();
        }

        aiModalTitle.textContent = 'Piksel Sayısı 4 Katına Çıkarılıyor';
        aiModalDesc.textContent = 'ESRGAN sinir ağı yeni pikseller üretiyor...';

        const upscaledSrc = await upscalerInstance.upscale(rawImage, {
          patchSize: 128,
          padding: 4,
          progress: (amount) => {
            const p = Math.max(15, Math.round(amount * 100));
            aiProgressFill.style.width = `${p}%`;
            aiProgressText.textContent = `${p}%`;
          }
        });

        const newImg = new Image();
        newImg.onload = () => {
          rawImage = newImg;
          if (sharpenPercent > 0) {
            currentImage = applySmartSharpen(rawImage, sharpenPercent / 100);
          } else {
            currentImage = rawImage;
          }
          // Boyut 2 katına çıktığı için ekrandaki kapladığı görsel alanı koru
          scale = scale / 2;
          baseFitScale = baseFitScale / 2;
          updateZoomUI();
          render();

          aiModal.classList.remove('active');
          isUpscaling = false;
        };
        newImg.src = upscaledSrc;
      } else {
        // Çevrimdışı / Alternatif 2x Yüksek Kalite Piksel İnterpolasyon Motoru
        aiModalTitle.textContent = 'Gelişmiş Çözünürlük Motoru Çalışıyor';
        aiProgressFill.style.width = '60%';
        aiProgressText.textContent = '60%';

        setTimeout(() => {
          const w = rawImage.width * 2;
          const h = rawImage.height * 2;
          const offCanvas = document.createElement('canvas');
          offCanvas.width = w;
          offCanvas.height = h;
          const offCtx = offCanvas.getContext('2d');
          offCtx.imageSmoothingEnabled = true;
          offCtx.imageSmoothingQuality = 'high';
          offCtx.drawImage(rawImage, 0, 0, w, h);

          const newImg = new Image();
          newImg.onload = () => {
            rawImage = newImg;
            if (sharpenPercent > 0) {
              currentImage = applySmartSharpen(rawImage, sharpenPercent / 100);
            } else {
              currentImage = rawImage;
            }
            scale = scale / 2;
            baseFitScale = baseFitScale / 2;
            updateZoomUI();
            render();

            aiProgressFill.style.width = '100%';
            aiProgressText.textContent = '100%';
            setTimeout(() => {
              aiModal.classList.remove('active');
              isUpscaling = false;
            }, 300);
          };
          newImg.src = offCanvas.toDataURL('image/png');
        }, 500);
      }
    } catch (err) {
      console.error('Upscale error:', err);
      aiModal.classList.remove('active');
      isUpscaling = false;
      alert('Yapay zeka netleştirme sırasında bir hata oluştu: ' + (err.message || err));
    }
  }

  btnAiUpscale.addEventListener('click', upscaleWithAI);

  // 8. İndirme & Paylaşma (Tam 1080x1350 Çözünürlükte)
  function downloadImage() {
    if (!currentImage) {
      alert('Lütfen önce bir ekran görüntüsü seçin.');
      return;
    }

    render(); // En güncel hali çiz

    const link = document.createElement('a');
    const timestamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
    link.download = `instagram_post_${timestamp}.png`;
    link.href = canvas.toDataURL('image/png', 1.0);
    link.click();
  }

  btnDownload.addEventListener('click', downloadImage);

  // Web Share API (Mobilde doğrudan Instagram / Galeriye Kaydet)
  btnShare.addEventListener('click', async () => {
    if (!currentImage) {
      alert('Lütfen önce bir ekran görüntüsü seçin.');
      return;
    }

    canvas.toBlob(async (blob) => {
      const file = new File([blob], 'instagram_post.png', { type: 'image/png' });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        try {
          await navigator.share({
            files: [file],
            title: 'Instagram Post',
            text: '1080x1350 Siyah Arka Planlı Gönderi'
          });
        } catch (err) {
          if (err.name !== 'AbortError') {
            downloadImage();
          }
        }
      } else {
        downloadImage();
      }
    }, 'image/png');
  });

  // Klavye Kısayolları (Desktop Hızı İçin)
  window.addEventListener('keydown', (e) => {
    if (!currentImage) return;

    const step = e.shiftKey ? 20 : 4;
    let handled = true;

    switch (e.key) {
      case 'ArrowLeft':
        posX -= step;
        checkSnapGuides();
        break;
      case 'ArrowRight':
        posX += step;
        checkSnapGuides();
        break;
      case 'ArrowUp':
        posY -= step;
        checkSnapGuides();
        break;
      case 'ArrowDown':
        posY += step;
        checkSnapGuides();
        break;
      case 'c':
      case 'C':
        centerImage();
        break;
      case '+':
      case '=':
        btnZoomIn.click();
        break;
      case '-':
      case '_':
        btnZoomOut.click();
        break;
      default:
        handled = false;
    }

    if (handled) {
      e.preventDefault();
      render();
    }
  });

  // İlk siyah tuvali çiz
  render();
})();
