/**
 * Boot VK Mini App / community plugin shell.
 * Without VKWebAppInit the client often stays on a blank/loading screen.
 */
(function () {
  'use strict';

  function isVkShell() {
    try {
      var q = String(location.search || '');
      if (/(?:^\?|&)vk_app_id=/.test(q) || /(?:^\?|&)vk_platform=/.test(q)) return true;
      if (window.parent && window.parent !== window) {
        var ref = String(document.referrer || '');
        if (/vk\.(com|ru)|ok\.ru|mail\.ru/i.test(ref)) return true;
      }
    } catch (e) {}
    return false;
  }

  function init() {
    var bridge = window.vkBridge || window.vkConnect;
    if (!bridge || typeof bridge.send !== 'function') return;
    try {
      bridge.send('VKWebAppInit', {});
    } catch (e) {}
    try {
      if (typeof bridge.subscribe === 'function') {
        bridge.subscribe(function () {});
      }
    } catch (e) {}
    // Help Leaflet reflow after VK chrome settles.
    setTimeout(function () {
      try {
        window.dispatchEvent(new Event('resize'));
      } catch (e) {}
    }, 400);
  }

  if (!isVkShell() && !(window.vkBridge || window.vkConnect)) {
    // Still attempt init if bridge script loaded (harmless outside VK).
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
