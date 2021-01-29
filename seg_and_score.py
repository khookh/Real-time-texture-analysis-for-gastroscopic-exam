#!/usr/bin/python

import numpy as np
import skimage.color
import skimage.viewer
import cv2 as cv
import queue
from threading import Thread
import time
import sys
import os


# segmentation (HSV)
def seg_hsv(img):
    img = cv.cvtColor(img, cv.COLOR_BGR2HSV)
    h, s, v = cv.split(img)
    # temp seg masks
    mask = cv.inRange(img, (0, 35, 170), (60, 100, 245))  # direct light
    mask2 = cv.inRange(img, (0, 0, 90), (30, 95, 170))  # low light foam
    return mask + mask2
    # return cv.bitwise_and(img, img, mask=mask)


# renvoie un score de qualité à partir de l'image binaire
def score(ima, _dim):
    scoring = 0
    bad_pixels = cv.findNonZero(ima)
    if bad_pixels is not None:
        scoring = bad_pixels.shape[0] / (4 * _dim[0] * _dim[1])
    return scoring


kernel = np.ones((9, 9), np.uint8)
kernelb = np.ones((3, 3), np.uint8)


# applique les transpho morphologiques à l'image
def morph_trans(ima):
    global kernel, kernelb
    ima = cv.morphologyEx(ima, cv.MORPH_CLOSE, kernel)  # clustering
    ima = cv.morphologyEx(ima, cv.MORPH_OPEN, kernelb)  # denoise
    ima = cv.morphologyEx(ima, cv.MORPH_OPEN, kernel)  # denoise
    # ima = cv.dilate(ima, np.ones((5, 5), np.uint8), iterations=1)
    return ima


# returns the uniformity of the image
def uniformity(ima):
    blur1_uni = cv.GaussianBlur(ima, (7, 7), 1)
    blur2_uni = cv.GaussianBlur(ima, (31, 31), 2)
    return np.sum((blur1_uni - blur2_uni) ** 2)


# Return True if the 6 previous frames are strictly different
def strict_diff():
    global blur_list
    if blur_list.size > 6:
        for i in range(6):
            if blur_list[-1 - i] == blur_list[-1 - i - 1]:
                return False
        return True
    return False


# Return True if the 4 previous frames are similar
def strict_eq():
    global blur_list
    if blur_list.size > 4:
        for i in range(4):
            if blur_list[-1 - i] != blur_list[-1 - i - 1]:
                return False
        return True
    return False


# output into thefile the score of the section that has been processed
def section_score():
    global f, score_list, section_score_list, section
    f.write("Mean score in section %i = %.2f \n" % (section, np.mean(section_score_list)))
    f.write("_____________________\n")
    score_list = np.append(score_list, section_score_list)
    section_score_list = np.array([])
    section += 1


# save the temporary score buffer into the section list
def save():
    global section_score_list, temp_score_list
    if temp_score_list.size > 8:
        section_score_list = np.append(section_score_list, temp_score_list)
    temp_score_list = np.array([])


# lecture flux vidéo
section, count = 1, 1
sco, unfy = 0, 0
p_capture = False
over = False
blur_list = np.array([])
score_list = np.array([])
temp_score_list = np.array([])
section_score_list = np.array([])
q_frame = queue.Queue()
q_treated = queue.Queue()
f = open("output_%s.txt" % os.path.basename(str(sys.argv[1])), "w")
cap = cv.VideoCapture(str(sys.argv[1]))

# Thread reading the video flux
def read_flux():
    global count, over, cap
    while not cap.isOpened():  # attente active en cas de lecture de flux en real-time, on attend le header
        cap = cv.VideoCapture(str(sys.argv[1]))
        cv.waitKey(500)
    while cap.isOpened():
        while q_frame.qsize() > 100:
            time.sleep(0)
        retr, frame = cap.read()
        if retr is not True and count > 1:
            cap.release()
            cv.destroyAllWindows()
            over = True
            break
        if retr is True:
            q_frame.put(cv.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv.INTER_CUBIC))
            count += 1
        if over is True:
            cap.release()
            cv.destroyAllWindows()
            break



# thread treating the frames
def frame_treatment():
    global temp_score_list, section_score_list, score_list, blur_list, count, section, p_capture, unfy, over
    local_count = 1
    dim = (0, 0)
    while True:
        if q_frame.empty():
            time.sleep(0)
        frame = q_frame.get()
        if local_count == 1:
            dimensions = frame.shape
            centrex, centrey = dimensions[1] / 2, dimensions[0] / 2
            dim = (int(centrex), int(centrey))
            frame_treated = np.zeros(dimensions)
        # uniformity
        unfy = uniformity(frame) / (dim[0] * dim[1] * 4)
        blur_list = np.append(blur_list, unfy)
        if p_capture is False and strict_eq():
            p_capture = True
            save()
        if p_capture is True and strict_diff():
            p_capture = False
            section_score()
            temp_score_list = np.array([])
        if unfy > 15:
            frame_treated = seg_hsv(frame)
            frame_treated = morph_trans(frame_treated)
            temp_score_list = np.append(temp_score_list, round(score(frame_treated, dim) * 100, 3))
        else:
            save()

        if over is True:
            cv.destroyAllWindows()
            save()
            section_score()
            break
        q_treated.put(frame)
        local_count += 1


# Thread displaying the frames
def display_t():
    global section_score_list, score_list, count, over
    local_count = 1
    while True:
        if q_treated.empty():
            time.sleep(0)
        frame = q_treated.get()  # [0]
        # Affichage
        frame = skimage.color.gray2rgb(frame)
        # resize pour affichage propre
        # concatene les deux images pour comparaison
        # numpy_h_concat = np.hstack((frame, frame_treated_f))
        # rajoute les paramètres informatifs
        image = cv.putText(frame, 'Frame %d' % local_count, (5, 370), cv.FONT_HERSHEY_SIMPLEX, .4, (0, 0, 255),
                           1,
                           cv.LINE_AA)
        image = cv.putText(image, 'mean score = %.2f' % np.mean(section_score_list), (5, 400),
                           cv.FONT_HERSHEY_SIMPLEX, .5,
                           (0, 0, 255), 1,
                           cv.LINE_AA)
        # image = cv.putText(image, 'uniformity = %d' % round(q_treated.get()[1]), (5, 420), cv.FONT_HERSHEY_SIMPLEX,
        # .5, (0, 0, 255), 1, cv.LINE_AA) show dans la fenêtre
        cv.imshow('comparison', image)
        local_count += 1
        # cv.imwrite('frames/resizeLINEAR%d.png' % local_count, image)
        k = cv.waitKey(1) & 0xFF
        if k == ord('p'):
            while True:
                if cv.waitKey(1) & 0xFF == ord('s'):
                    break
        if k == ord('q') or over is True:
            over = True
            cv.destroyAllWindows()
            break


thread_fetch = Thread(target=read_flux)
thread_treatment = Thread(target=frame_treatment)
thread_display = Thread(target=display_t)
thread_fetch.start()
thread_treatment.start()
thread_display.start()

# thread treatment stops when either the display or the fetch has stopped
thread_treatment.join()

f.write("Mean score of whole video = %.2f \n" % np.mean(score_list))
f.write("(%.2f %% of the frame from the video were treated)" % (score_list.size * 100.0 / count))
f.close()
