"""Bounded playback-reference rejection, not a full acoustic echo canceller.
Only subtract strongly correlated playback; retain independent near-end speech.
"""
import threading
import time
import numpy as np
from scipy.signal import correlate, resample_poly
from math import gcd

class PlaybackEcho:
    def __init__(self, rate=16000):
        self.rate=rate
        self.lock=threading.Lock()
        self.samples=None
        self.started=0.0
        self.stopped=None

    def begin(self, samples, rate):
        pcm=np.asarray(samples,dtype=np.float32)
        if pcm.ndim>1: pcm=pcm.mean(axis=1)
        divisor=gcd(int(rate),self.rate)
        pcm=resample_poly(pcm,self.rate//divisor,int(rate)//divisor).astype(np.float32)
        with self.lock:
            self.samples=pcm;self.started=time.monotonic();self.stopped=None

    def end(self):
        with self.lock:self.stopped=time.monotonic()

    def filter(self, frame):
        now=time.monotonic()
        with self.lock:
            if self.samples is None:return frame
            if self.stopped is not None and now-self.stopped>.5:
                self.samples=None
                return frame
            elapsed=(self.stopped or now)-self.started
            lo=max(0,int((elapsed-1.0)*self.rate))
            hi=min(len(self.samples),int((elapsed+.15)*self.rate))
            reference=self.samples[lo:hi]
        x=np.frombuffer(frame,dtype=np.int16).astype(np.float32)/32768
        n=len(x)
        energy=float(x@x)
        if not n or energy<1e-9 or len(reference)<n:return frame
        dots=correlate(reference,x,mode='valid',method='fft')
        summed=np.concatenate(([0.0],np.cumsum(reference*reference,dtype=np.float64)))
        powers=summed[n:]-summed[:-n]
        scores=np.abs(dots)/np.sqrt(np.maximum(powers*energy,1e-12))
        at=int(np.argmax(scores))
        if scores[at]<.72:return frame
        ref=reference[at:at+n]
        gain=float(dots[at]/max(powers[at],1e-12))
        residual=x-gain*ref
        # Suppress small residuals of a strong echo match, keep mixed user speech.
        if float(residual@residual)<energy*.12:residual=np.zeros_like(x)
        return (np.clip(residual,-1, .999969)*32768).astype(np.int16).tobytes()
