/* Presentation controls. Geographic data, scoring and layer rendering stay in each map page. */
(function () {
  'use strict';
  const nav = document.querySelector('nav.gnb');
  const menu = document.querySelector('.menu-toggle');
  if (nav && menu) {
    nav.classList.add('enhanced');
    const closeMenu = function () {
      nav.classList.remove('menu-open');
      menu.setAttribute('aria-expanded', 'false');
    };
    menu.addEventListener('click', function () {
      const open = nav.classList.toggle('menu-open');
      menu.setAttribute('aria-expanded', String(open));
    });
    nav.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && nav.classList.contains('menu-open')) {
        closeMenu();
        menu.focus();
      }
    });
    nav.querySelectorAll('.links a').forEach(function (link) {
      link.addEventListener('click', closeMenu);
    });
  }

  const panel = document.querySelector('details.panel');
  if (panel && window.matchMedia('(max-width: 760px)').matches) {
    panel.open = false;
  }
  const region = document.getElementById('regionSelect');
  const regionGo = document.getElementById('regionGo');
  if (region && regionGo) {
    regionGo.addEventListener('click', function () {
      window.location.assign(region.value);
    });
  }

  // A mobile menu changes the map viewport height. Kakao needs an explicit relayout.
  const mapElement = document.getElementById('map');
  if (mapElement && 'ResizeObserver' in window) {
    let frame;
    const observer = new ResizeObserver(function () {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(function () {
        if (typeof map !== 'undefined' && map && typeof map.relayout === 'function') {
          const center = map.getCenter();
          map.relayout();
          map.setCenter(center);
        }
      });
    });
    observer.observe(mapElement);
  }
})();
