"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const oldRoutes = require("./base/lib/routes");
const oldRef = require("./base/lib/whatsapp-ref");
const newRoutes = require("./lib/routes");
const newRef = require("./lib/whatsapp-ref");
const routing_1 = require("./i18n/routing");
const before = oldRef.whatsappRefPages();
const after = newRef.whatsappRefPages();
const changed = Object.keys(before).filter(path => after[path] !== before[path]);
console.log('existing ref entries:', Object.keys(before).length, 'changed:', changed.length, 'added:', Object.keys(after).length - Object.keys(before).length);
const paths = Object.keys(before);
let diff = 0;
for (const path of paths)
    for (const target of routing_1.locales) {
        if (oldRoutes.translateCurrentPath(encodeURI(path), target) !== newRoutes.translateCurrentPath(encodeURI(path), target))
            diff++;
    }
console.log('translateCurrentPath checks:', paths.length * routing_1.locales.length, 'different:', diff);
if (changed.length || diff)
    process.exitCode = 1;
