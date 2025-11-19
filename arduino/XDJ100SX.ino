#include <Bounce.h>
#include <Encoder.h>
#include <elapsedMillis.h>
#include <ResponsiveAnalogRead.h>


// MIDI IN - botons
const int eject_pin = 0;
const int track_previous_pin = 1;
const int track_next_pin = 2;
const int search_back_pin = 3;
const int search_forward_pin = 4;
const int cue_pin = 5;
const int play_pin = 6;
const int jet_pin = 7;
const int zip_pin = 8;
const int wah_pin = 9;
const int hold_pin = 10;
const int time_pin = 11;
const int mastertempo_pin = 12;

//encoder jog
const int jogA_pin = 20;
const int jogB_pin = 15;
const int midiChannel = 2;
const int jogControlNumber = 20;
Encoder jog(jogA_pin, jogB_pin);
long lastPosition_jog = 0;



//encoder browser
const int browseA_pin = 22;
const int browseB_pin = 21;
const int load_pin= 23;
const int midiChannelb = 3;
const int DEBOUNCE_MS = 3;    // Debounce curt
const int NOTE_SCROLL_DOWN = 70;
const int NOTE_SCROLL_UP = 71;
elapsedMillis debounceTime_browse;  // Temps per filtrar rebots browse¡
Encoder browse(browseA_pin, browseB_pin);
long lastPosition_browse = 0;       // Última posició llegida

elapsedMillis msec = 0;


/* Pitch slider old
const int pitch_pin = A0;
const int channel_pitch = 3;
const int controllerA0 = 7;
int previousA0 = -1;
ResponsiveAnalogRead analog(pitch_pin, true);
*/


//Pitch new

const int pitchPin = A0;
ResponsiveAnalogRead analog(pitchPin, true);
int lastMSB = -1;
int lastLSB = -1;



// MIDI OUT - Leds

const int ledCue = 16;
const int ledPlay = 17;
const int ledIntern = 18;
const int ledCd = 19;

// Canals MIDI
const  int channel = 1;

//Notes que rebo de Mixxx pel play, cue, etc
const int PLAY_NOTE_INDICATOR = 61;
const int CUE_NOTE_INDICATOR = 62;
const int LEDINTERN_NOTE_INDICATOR = 63;
const int LEDCD_NOTE_INDICATOR = 64;
const int SIESTAPLAY_NOTE_INDICATOR = 65;
bool siestaplay = false;

//Parpadeig final de track
bool parpadeig = false;
unsigned long tempsAnterior = 0;



//Bounce botons cada 5ms
Bounce eject_boto = Bounce (eject_pin, 50);
Bounce trackprevious_boto = Bounce (track_previous_pin, 50);
Bounce track_next_boto = Bounce (track_next_pin, 50);
Bounce search_back_boto = Bounce (search_back_pin, 50);
Bounce search_forward_boto = Bounce (search_forward_pin, 50);
Bounce play_boto = Bounce (play_pin, 50);
Bounce cue_boto = Bounce (cue_pin, 50);
Bounce jet_boto = Bounce (jet_pin, 50);
Bounce zip_boto = Bounce (zip_pin, 50);
Bounce wah_boto = Bounce (wah_pin, 50);
Bounce hold_boto = Bounce (hold_pin, 50);
Bounce time_boto = Bounce (time_pin, 50);
Bounce mastertempo_boto = Bounce (mastertempo_pin, 50);
Bounce load_boto = Bounce (load_pin, 50);




// --- FUNCIONS QUE S'EXECUtEN QUAN ES REP UN MISSATGE MIDI ---


// Aquesta funció s'executarà automàticament quan es rebi un "Note On"
void handleNoteOn(byte channel, byte note, byte velocity) {
 // Comprovem si la nota rebuda és la del nostre indicador de Play
 if (note == PLAY_NOTE_INDICATOR) {
   // Si la velocitat és més gran que 0, vol dir "Play", així que encenem el LED
   if (velocity > 0) {
     digitalWrite(ledPlay, HIGH);
   }
   // Si la velocitat és 0, es tracta com un Note Off, així que l'apaguem
   else {
     digitalWrite(ledPlay, LOW);
   }
 }
 if (note == CUE_NOTE_INDICATOR) {
   // Si la velocitat és més gran que 0, vol dir "Play", així que encenem el LED
   if (velocity > 0) {
     digitalWrite(ledCue, HIGH);
   }
   // Si la velocitat és 0, es tracta com un Note Off, així que l'apaguem
   else {
     digitalWrite(ledCue, LOW);
   }
 }
//LED INTERN MARCA EL BPM, NOMÉS SI ESTÀ EN PLAY
if(note == SIESTAPLAY_NOTE_INDICATOR){
  siestaplay = true;
}
if (note == LEDINTERN_NOTE_INDICATOR && siestaplay == true)
{
  digitalWrite(ledIntern, HIGH);
} 
 //LED CD el farem parpadejar quan rebi informació que la cançó s'està acabant (mixxx envia 1)
 if (note == LEDCD_NOTE_INDICATOR) {
    parpadeig = (velocity > 0);
    }

    
}


// Aquesta funció s'executarà automàticament quan es rebi un "Note Off"
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
  digitalWrite(ledIntern, LOW);
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

pinMode(eject_pin, INPUT_PULLUP);
pinMode(track_previous_pin, INPUT_PULLUP);
pinMode(track_next_pin, INPUT_PULLUP);
pinMode(search_back_pin, INPUT_PULLUP);
pinMode(search_forward_pin, INPUT_PULLUP);
pinMode(cue_pin, INPUT_PULLUP);
pinMode(play_pin, INPUT_PULLUP);
pinMode(jet_pin, INPUT_PULLUP);
pinMode(eject_pin, INPUT_PULLUP);
pinMode(zip_pin, INPUT_PULLUP);
pinMode(wah_pin, INPUT_PULLUP);
pinMode(hold_pin, INPUT_PULLUP);
pinMode(time_pin, INPUT_PULLUP);
pinMode(mastertempo_pin, INPUT_PULLUP);
pinMode(load_pin, INPUT_PULLUP);


pinMode(ledCue, OUTPUT);
pinMode(ledPlay, OUTPUT);
pinMode(ledIntern, OUTPUT);
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
time_boto.update();
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
if(time_boto.fallingEdge()){
   usbMIDI.sendNoteOn(72, 127, channel); 
 }
 if(time_boto.risingEdge()){
   usbMIDI.sendNoteOff(72, 0, channel); 
 }
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
