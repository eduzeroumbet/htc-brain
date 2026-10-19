declare const process:{exitCode?:number};
import * as oldRoutes from './base/lib/routes';
import * as oldRef from './base/lib/whatsapp-ref';
import * as newRoutes from './lib/routes';
import * as newRef from './lib/whatsapp-ref';
import {locales} from './i18n/routing';
const before=oldRef.whatsappRefPages();const after=newRef.whatsappRefPages();
const changed=Object.keys(before).filter(path=>after[path]!==before[path]);
console.log('existing ref entries:',Object.keys(before).length,'changed:',changed.length,'added:',Object.keys(after).length-Object.keys(before).length);
const paths=Object.keys(before);let diff=0;
for(const path of paths)for(const target of locales){if(oldRoutes.translateCurrentPath(encodeURI(path),target)!==newRoutes.translateCurrentPath(encodeURI(path),target))diff++;}
console.log('translateCurrentPath checks:',paths.length*locales.length,'different:',diff);
if(changed.length||diff)process.exitCode=1;
