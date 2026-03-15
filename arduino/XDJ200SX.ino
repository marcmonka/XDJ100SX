#include <Bounce2.h>  // aktuelle Bounce2-Library nutzen
#include <Encoder.h>
#include <elapsedMillis.h>
#include <ResponsiveAnalogRead.h>


// ---------------- Button Pins ----------------
const int search_back_pin          = 12;
const int search_forward_pin       = 13;
const int track_previous_pin       = 14;
const int track_next_pin           = 15;
const int foldersearch_back_pin    = 16;
const int foldersearch_forward_pin = 17;
const int tempomode_pin            = 20;
const int mastertempo_pin          = 21;
const int load_pin                 = 24;  //Encoder Push Button
const int cue_pin                  = 25;
const int play_pin                 = 26;
const int autocue_pin              = 27;
const int beatloop_pin             = 28;
const int eject_pin                = 30;
const int jet_pin                  = 39;
const int zip_pin                  = 40;
const int wah_pin                  = 41;
const int hold_pin                 = 42;
const int loopin_pin               = 43;
const int loopout_pin              = 44;
const int reloop_pin               = 45;


// ---------------- Encoder Jogwheel ----------------
const int jogA_pin = 18;
const int jogB_pin = 19;
const int midiChannel = 2;
const int jogControlNumber = 20;
Encoder jog(jogA_pin, jogB_pin);
long lastPosition_jog = 0;


// ---------------- Encoder Browser ----------------
const int browseA_pin = 36;
const int browseB_pin = 37;   
const int midiChannelb = 3;
const int DEBOUNCE_MS = 3;    // Debounce curt
const int NOTE_SCROLL_DOWN = 70;
const int NOTE_SCROLL_UP = 71;
elapsedMillis debounceTime_browse;  // Temps per filtrar rebots browse¡
Encoder browse(browseA_pin, browseB_pin);
long lastPosition_browse = 0;       // Última posició llegida

elapsedMillis msec = 0;


// ---------------- Pitch ----------------
const int pitchPin = A0;
ResponsiveAnalogRead analog(pitchPin, true);
int lastMSB = -1;
int lastLSB = -1;


// ---------------- LED Pins ----------------
const int ledCue  = 7;
const int ledPlay = 6;
const int ledLoopIn = 8;
const int ledLoopOut = 9;
const int ledLoop = 10;
const int ledMastertempo = 11;
const int ledJog1 = 1;
const int ledJog2 = 2;
const int ledJog3 = 3;
const int ledJog4 = 4;
const int ledJog5 = 5;
const int ledCd = 29;


// ---------------- MIDI Channels ----------------
const  int channel = 1;


// ---------------- Notes, received from Mixxx  ----------------
const int PLAY_NOTE_INDICATOR = 61;
const int CUE_NOTE_INDICATOR = 62;
const int LEDINTERN_NOTE_INDICATOR = 63;
const int LEDCD_NOTE_INDICATOR = 64;
const int SIESTAPLAY_NOTE_INDICATOR = 65;
bool siestaplay = false;


// ---------------- Blink when the track ends  ----------------
bool parpadeig = false;
unsigned long tempsAnterior = 0;


// ---------------- Bounce buttons 5ms ----------------
Bounce search_back_boto = Bounce (search_back_pin, 50);
Bounce search_forward_boto = Bounce (search_forward_pin, 50);
Bounce trackprevious_boto = Bounce (track_previous_pin, 50);
Bounce track_next_boto = Bounce (track_next_pin, 50);
Bounce foldersearch_back_boto = Bounce (foldersearch_back_pin, 50);
Bounce foldersearch_forward_boto = Bounce (foldersearch_forward_pin, 50);
Bounce tempomode_boto = Bounce (tempomode_pin, 50);
Bounce mastertempo_boto = Bounce (mastertempo_pin, 50);
Bounce load_boto = Bounce (load_pin, 50);
Bounce cue_boto = Bounce (cue_pin, 50);
Bounce play_boto = Bounce (play_pin, 50);
Bounce autocue_boto = Bounce (autocue_pin, 50);
Bounce beatloop_boto = Bounce (beatloop_pin, 50);
Bounce eject_boto = Bounce (eject_pin, 50);
Bounce jet_boto = Bounce (jet_pin, 50);
Bounce zip_boto = Bounce (zip_pin, 50);
Bounce wah_boto = Bounce (wah_pin, 50);
Bounce hold_boto = Bounce (hold_pin, 50);
Bounce loopin_boto = Bounce (loopin_pin, 50);
Bounce loopout_boto = Bounce (loopout_pin, 50);
Bounce reloop_boto = Bounce (reloop_pin, 50);

//Bounce time_boto = Bounce (time_pin, 50);


// --- Execute Function if receiving a MIDI Message ---

// Execute Automatically if receiving a "Note On"
void handleNoteOn(byte channel, byte note, byte velocity) {
 // Check if the "Note On" is "PLAY"
 if (note == PLAY_NOTE_INDICATOR) {
   // If the speed is greater than 0, it means "Play", so we turn on the LED
   if (velocity > 0) {
     digitalWrite(ledPlay, HIGH);
   }
   // If the velocity is 0, it is treated as a Note Off, so we turn the LED off.
   else {
     digitalWrite(ledPlay, LOW);
   }
 }
 if (note == CUE_NOTE_INDICATOR) {
   // If the speed is greater than 0, it means "Cue", so we turn on the LED
   if (velocity > 0) {
     digitalWrite(ledCue, HIGH);
   }
   // If the velocity is 0, it is treated as a Note Off, so we turn the LED off.
   else {
     digitalWrite(ledCue, LOW);
   }
 }

 
// INTERNAL LED MARK THE BPM, ONLY IF IT IS IN PLAY
if(note == SIESTAPLAY_NOTE_INDICATOR){
  siestaplay = true;
}
if (note == LEDINTERN_NOTE_INDICATOR && siestaplay == true)
{
  digitalWrite(ledJog1, HIGH);
  digitalWrite(ledJog2, HIGH);
  digitalWrite(ledJog3, HIGH);
  digitalWrite(ledJog4, HIGH);
  digitalWrite(ledJog5, HIGH);
} 
 // make the CD LED blink when it receives information that the song is ending
 if (note == LEDCD_NOTE_INDICATOR) {
    parpadeig = (velocity > 0);
    }

    
}


// Execute Automatically if receiving a "Note Off"
void handleNoteOff(byte channel, byte note, byte velocity) {
 // Comprovem si la nota rebuda és la del nostre indicador de Play
 if (note == PLAY_NOTE_INDICATOR) {
   // Si rebem un Note Off per a aquesta nota, apaguem el LED
   digitalWrite(ledPlay, LOW);
 }
 if (note == CUE_NOTE_INDICATOR) {
   // Si rebem un Note Off per a aquesta nota, apaguem el LED
   digitalWrite(ledCue, LOW);
 }
 
 if (note == LEDCD_NOTE_INDICATOR) {
   parpadeig = false;
 }

 if(note == SIESTAPLAY_NOTE_INDICATOR){
  siestaplay = false;
 }
 if (note == LEDINTERN_NOTE_INDICATOR || siestaplay == false){
  digitalWrite(ledJog1, LOW);
  digitalWrite(ledJog2, LOW);
  digitalWrite(ledJog3, LOW);
  digitalWrite(ledJog4, LOW);
  digitalWrite(ledJog5, LOW);
 }

}

void JogNudge(){
  long newPosition_jog = jog.read();
  
  if (newPosition_jog % 4 == 0 && newPosition_jog != lastPosition_jog) {
    if (newPosition_jog > lastPosition_jog) {
      // Dreta -> Envia 65
      usbMIDI.sendControlChange(jogControlNumber, 65, midiChannel);
    } else {
      // Esquerra -> Envia 63
      usbMIDI.sendControlChange(jogControlNumber, 63, midiChannel);
    }
    lastPosition_jog = newPosition_jog;
  }

}


void setup() {

pinMode(search_back_pin, INPUT_PULLUP);
pinMode(search_forward_pin, INPUT_PULLUP);
pinMode(track_previous_pin, INPUT_PULLUP);
pinMode(track_next_pin, INPUT_PULLUP);
pinMode(foldersearch_back_pin, INPUT_PULLUP);
pinMode(foldersearch_forward_pin, INPUT_PULLUP);
pinMode(tempomode_pin, INPUT_PULLUP);
pinMode(mastertempo_pin, INPUT_PULLUP);
pinMode(load_pin, INPUT_PULLUP);
pinMode(cue_pin, INPUT_PULLUP);
pinMode(play_pin, INPUT_PULLUP);
pinMode(autocue_pin, INPUT_PULLUP);
pinMode(beatloop_pin, INPUT_PULLUP);
pinMode(eject_pin, INPUT_PULLUP);
pinMode(jet_pin, INPUT_PULLUP);
pinMode(zip_pin, INPUT_PULLUP);
pinMode(wah_pin, INPUT_PULLUP);
pinMode(hold_pin, INPUT_PULLUP);
pinMode(loopin_pin, INPUT_PULLUP);
pinMode(loopout_pin, INPUT_PULLUP);
pinMode(reloop_pin, INPUT_PULLUP);


pinMode(ledCue, OUTPUT);
pinMode(ledPlay, OUTPUT);
pinMode(ledLoopIn, OUTPUT);
pinMode(ledLoopOut, OUTPUT);
pinMode(ledLoop, OUTPUT);
pinMode(ledMastertempo, OUTPUT);
pinMode(ledJog1, OUTPUT);
pinMode(ledJog2, OUTPUT);
pinMode(ledJog3, OUTPUT);
pinMode(ledJog4, OUTPUT);
pinMode(ledJog5, OUTPUT);
pinMode(ledCd, OUTPUT);


 // --- CONFIGURació MIDI ---
 // Assignem les nostres funcions "callback" als esdeveniments MIDI
 usbMIDI.setHandleNoteOn(handleNoteOn);
 usbMIDI.setHandleNoteOff(handleNoteOff);

 //Inicialitzo jog
 jog.write(0);

 //Inicialitzo browse
 browse.write(0);
 lastPosition_browse = 0;

}

void loop() {

eject_boto.update();
trackprevious_boto.update();
track_next_boto.update();
search_back_boto.update();
search_forward_boto.update();
cue_boto.update();
play_boto.update();
jet_boto.update();
zip_boto.update();
wah_boto.update();
hold_boto.update();
//time_boto.update();
mastertempo_boto.update();
load_boto.update();


//Play
 if(play_boto.fallingEdge()){
   usbMIDI.sendNoteOn(60, 127, channel); 
 }
 if(play_boto.risingEdge()){
   usbMIDI.sendNoteOff(60, 0, channel); 
 }
 //CUE
 if(cue_boto.fallingEdge()){
   usbMIDI.sendNoteOn(61, 127, channel); 
 }
 if(cue_boto.risingEdge()){
   usbMIDI.sendNoteOff(61, 0, channel); 
 }


//Master Tempo
 if(mastertempo_boto.fallingEdge()){
   usbMIDI.sendNoteOn(62, 127, channel); 
 }
 if(mastertempo_boto.risingEdge()){
   usbMIDI.sendNoteOff(62, 0, channel); 
 }

//Eject
if(eject_boto.fallingEdge()){
   usbMIDI.sendNoteOn(63, 127, channel); 
 }
 if(eject_boto.risingEdge()){
   usbMIDI.sendNoteOff(63, 0, channel); 
 }
 //trackprevious
if(trackprevious_boto.fallingEdge()){
   usbMIDI.sendNoteOn(64, 127, channel); 
 }
 if(trackprevious_boto.risingEdge()){
   usbMIDI.sendNoteOff(64, 0, channel); 
 }
 //tracknext
if(track_next_boto.fallingEdge()){
   usbMIDI.sendNoteOn(65, 127, channel); 
 }
 if(track_next_boto.risingEdge()){
   usbMIDI.sendNoteOff(65, 0, channel); 
 }
  //search_back
if(search_back_boto.fallingEdge()){
   usbMIDI.sendNoteOn(66, 127, channel); 
 }
 if(search_back_boto.risingEdge()){
   usbMIDI.sendNoteOff(66, 0, channel); 
 }
   //search_forward
if(search_forward_boto.fallingEdge()){
   usbMIDI.sendNoteOn(67, 127, channel); 
 }
 if(search_forward_boto.risingEdge()){
   usbMIDI.sendNoteOff(67, 0, channel); 
 }
    //jet
if(jet_boto.fallingEdge()){
   usbMIDI.sendNoteOn(68, 127, channel); 
 }
 if(jet_boto.risingEdge()){
   usbMIDI.sendNoteOff(68, 0, channel); 
 }
     //zip
if(zip_boto.fallingEdge()){
   usbMIDI.sendNoteOn(69, 127, channel); 
 }
 if(zip_boto.risingEdge()){
   usbMIDI.sendNoteOff(69, 0, channel); 
 }
     //wah
if(wah_boto.fallingEdge()){
   usbMIDI.sendNoteOn(70, 127, channel); 
 }
 if(wah_boto.risingEdge()){
   usbMIDI.sendNoteOff(70, 0, channel); 
 }
     //hold
if(hold_boto.fallingEdge()){
   usbMIDI.sendNoteOn(71, 127, channel); 
 }
 if(hold_boto.risingEdge()){
   usbMIDI.sendNoteOff(71, 0, channel); 
 }
     //time
//if(time_boto.fallingEdge()){
//   usbMIDI.sendNoteOn(72, 127, channel); 
// }
// if(time_boto.risingEdge()){
//   usbMIDI.sendNoteOff(72, 0, channel); 
// }
     //load
if(load_boto.fallingEdge()){
   usbMIDI.sendNoteOn(73, 127, channel); 
 }
 if(load_boto.risingEdge()){
   usbMIDI.sendNoteOff(73, 0, channel); 
 }


 //Jog: cridem la funció JogNudge
JogNudge();


//Browse
long newPosition_browse = browse.read();
  long delta_browse = newPosition_browse - lastPosition_browse;

  if (debounceTime_browse > DEBOUNCE_MS && delta_browse != 0) {
    // Convertim els passos de l'encoder a "clics" (canvis de +1 o -1)
    // LA CLAU ÉS AQUÍ: Només actuem si la posició és un múltiple de 4
  // i si és diferent de l'última posició VÀLIDA que vam guardar.
  if (newPosition_browse % 4 == 0 && newPosition_browse != lastPosition_browse) {
    
    if (newPosition_browse > lastPosition_browse) {
      // Direcció: DRETA (baixar a la llista)
      usbMIDI.sendNoteOn(NOTE_SCROLL_DOWN, 127, midiChannelb);
      usbMIDI.sendNoteOff(NOTE_SCROLL_DOWN, 0, midiChannelb);

    } else {
      // Direcció: ESQUERRA (pujar a la llista)
      usbMIDI.sendNoteOn(NOTE_SCROLL_UP, 127, midiChannelb);
      usbMIDI.sendNoteOff(NOTE_SCROLL_UP, 0, midiChannelb);
    }
    
    // Actualitzem la posició "antiga" NOMÉS quan tenim un clic complet.
    lastPosition_browse = newPosition_browse;
  }
}

/* Pitch old
if (msec >= 100){
  msec = 0;
  int n0 = analogRead(A0) / 8;
  //transmetre MIDI si A0 canvia
  if(n0 != previousA0){
    usbMIDI.sendControlChange(controllerA0, n0, channel_pitch);
    previousA0 = n0;
   }
}
*/

//Pitch 14 bits

analog.update();
  int raw = analog.getValue();   // valor ja suavitzat

  int value14 = map(raw, 0, 1023, 0, 16383);

  byte msb = (value14 >> 7) & 0x7F;
  byte lsb = value14 & 0x7F;

  if (msb != lastMSB) {
    usbMIDI.sendControlChange(0, msb, 1);
    lastMSB = msb;
  }

  if (lsb != lastLSB) {
    usbMIDI.sendControlChange(32, lsb, 1);
    lastLSB = lsb;
  }




//Parpadeig LED CD si s'acaba la cançó (MIXX envia 127)
if (parpadeig){
  if (millis () - tempsAnterior >= 1000){
    tempsAnterior = millis();
    digitalWrite(ledCd, !digitalRead(ledCd));
  }
}
else{
    digitalWrite(ledCd, LOW);
  }

// Aquesta línia és l'única cosa que necessitem al loop.
 // Constantment comprova si ha arribat algun missatge de Mixxx
 // i, si és així, crida automàticament a les funcions 'handleNoteOn' o 'handleNoteOff'.
 while (usbMIDI.read()){};


}
