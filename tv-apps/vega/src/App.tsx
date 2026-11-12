// guest-tv on Fire TV (Vega OS): the whole app is Amazon's WebView showing guest-tv's TV page.
// Written from Amazon's WebView guide (developer.amazon.com/docs/vega/2.0/develop-your-app-with-webview),
// from couch-tv's Vega app. Copy this over src/App.tsx of a project made with `vega project generate`,
// then see tv-apps/vega/README.md.
import React from 'react';
import { WebView } from '@amazon-devices/webview';
import { View } from 'react-native';
// guest.json is written by make-config.py (never committed): { "url": "http://<computer>:5410", "tv": "<home id>" }
import guest from './guest.json';

export const App = () => {
  // keys=1 tells the page to ask the computer for the phone remote's keys and press them on itself.
  // There is no key or password in this address.
  const uri = guest.url + '/tv/?tv=' + encodeURIComponent(guest.tv) + '&brand=vega&keys=1';
  return (
    <View style={{ flex: 1, backgroundColor: '#000' }}>
      <WebView
        source={{ uri }}
        javaScriptEnabled={true}
        hasTVPreferredFocus={true}
        allowSystemKeyEvents={true}
        style={{ flex: 1, backgroundColor: '#000' }}
      />
    </View>
  );
};
