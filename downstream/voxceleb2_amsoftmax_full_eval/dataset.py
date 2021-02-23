import torch
from torch.utils.data import DataLoader, Dataset
import numpy as np 
from librosa.util import find_files
from torchaudio import load
from torch import nn
from pathlib import Path
import os 
import IPython 
import pdb
import random
import torchaudio
import sys
import time
import tqdm
import pickle
from sox import Transformer
from torchaudio.sox_effects import apply_effects_file


EFFECTS = [
["channels", "1"],
["rate", "16000"],
["gain", "-3.0"],
["silence", "1", "0.1", "0.1%", "-1", "0.1", "0.1%"],
]

# Voxceleb 2 Speaker verification with plda
class SpeakerVerifi_plda(Dataset):
    def __init__(self, vad_config, file_path, key_list, meta_data, max_timestep=None):
    
        self.roots = file_path
        self.root_key = key_list
        self.max_timestep = max_timestep
        self.vad_c = vad_config 
        self.dataset = []
        self.all_speakers = []
        
        for index in range(len(self.root_key)):
            
            cache_path = f"./downstream/voxceleb2_amsoftmax_full_eval/cache_wav_paths/cache_{self.root_key[index]}.p"
            p = Path(self.roots[index])
            # loca cache_path if file exists
            if os.path.isfile(cache_path):

                # cache dict = 
                #{"speaker_id1":["wav_a_path1","wav_a_path2",...],"speaker_id2":["wav_b_path1", "wav_b_path2", ....],...}
                cache_wavs_dict = pickle.load(open(cache_path,"rb"))
                self.all_speakers.extend(list(cache_wavs_dict.keys()))
                for speaker_id in list(cache_wavs_dict.keys()):
                    for wavs in cache_wavs_dict[speaker_id]:
                        utterance_id = "/".join(str(p/speaker_id/wavs).split("/")[-3:]).replace(".wav","").replace("/","-")
                        self.dataset.append([str(p / speaker_id / wavs), utterance_id])
                        
            else:

                speaker_wav_dict = {}
                # calculate speakers and support to remove black list speaker (dev)
                speaker_dirs = [f.path.split("/")[-1] for f in os.scandir(self.roots[index]) if f.is_dir()]
                self.all_speakers.extend(speaker_dirs)
                    
                print("search all wavs paths")
                start = time.time()

                for speaker in tqdm.tqdm(speaker_dirs):
                    speaker_dir =  p / speaker
                    wav_list=find_files(speaker_dir)
                    speaker_wav_dict[speaker] = []
                    for wav in wav_list:
                        wav_sample, _ = apply_effects_file(str(speaker_dir/wav), EFFECTS)
                        wav_sample = wav_sample.squeeze(0)
                        length = wav_sample.shape[0]

                        if length > self.vad_c['min_sec']: 
                            utterance_id = "/".join(str(speaker_dir/wav).split("/")[-3:]).replace(".wav","").replace("/","-")
                            self.dataset.append([str(speaker_dir/wav), utterance_id])
                            speaker_wav_dict[speaker].append("/".join(wav.split("/")[-2:]))
                end = time.time() 

                print(f"search all wavs paths costs {end-start} seconds")
                print(f"save wav paths to {cache_path}! so we can directly load all_path in next time!")
                pickle.dump(speaker_wav_dict, open(cache_path,"wb"))    

        self.speaker_num = len(self.all_speakers)
        self.necessary_dict = self.processing()
        self.label_mapping_spk_id = {}
        # speaker id  map to speaker num
        self.build_label_mapping()

        self.label=self.build_label(self.dataset)

    def processing(self):
        
        speaker_num = len(self.all_speakers)
        return {"spk_paths":self.all_speakers,"total_spk_num":speaker_num,"pair_table":None}

    
    # file_path/id0001/asfsafs/xxx.wav
    def build_label_mapping(self):
        spk_count  = 0
        for speaker_id in self.all_speakers:
            self.label_mapping_spk_id[speaker_id.split("/")[-1]] = spk_count
            spk_count +=1
        
    
    def build_label(self,train_path_list):
        y = []
        for path in train_path_list:
            id_string = path[0].split("/")[-3]
            y.append(self.label_mapping_spk_id[id_string])

        return y

    def __len__(self):
        return len(self.dataset)
    
    def __getitem__(self, idx):
        wav, _ = apply_effects_file(str(self.dataset[idx][0]), EFFECTS)
        wav = wav.squeeze(0)
        length = wav.shape[0]

        if self.max_timestep !=None:
            if length > self.max_timestep:
                start = random.randint(0, int(length-self.max_timestep))
                wav = wav[start:start+self.max_timestep]
                length = self.max_timestep
  
        return wav, self.dataset[idx][1]
        
    def collate_fn(self, samples):
        
        wavs, idxes, labels = [], [], []

        for wav,idx in samples:
            wavs.append(wav)
            idxes.append(idx)
            labels.append(None)

        return wavs, idxes, labels


# Voxceleb 2 Speaker verification
class SpeakerVerifi_train(Dataset):
    def __init__(self, vad_config, key_list, file_path, meta_data, max_timestep=None):
    
        self.roots = file_path
        self.root_key = key_list
        self.max_timestep = max_timestep
        self.vad_c = vad_config 
        self.dataset = []
        self.all_speakers = []

        for index in range(len(self.root_key)):
            
            cache_path = f"./downstream/voxceleb2_amsoftmax_full_eval/cache_wav_paths/cache_{self.root_key[index]}.p"
            p = Path(self.roots[index])
            # loca cache_path if file exists
            if os.path.isfile(cache_path):

                # cache dict = 
                #{"speaker_id1":["wav_a_path1","wav_a_path2",...],"speaker_id2":["wav_b_path1", "wav_b_path2", ....],...}
                cache_wavs_dict = pickle.load(open(cache_path,"rb"))
                self.all_speakers.extend(list(cache_wavs_dict.keys()))
                for speaker_id in list(cache_wavs_dict.keys()):
                    for wavs in cache_wavs_dict[speaker_id]:
                        utterance_id = "/".join(str(p/speaker_id/wavs).split("/")[-3:]).replace(".wav","").replace("/","-")                        
                        self.dataset.append([str(p / speaker_id / wavs), utterance_id])

            else:

                speaker_wav_dict = {}
                # calculate speakers and support to remove black list speaker (dev)
                speaker_dirs = [f.path.split("/")[-1] for f in os.scandir(self.roots[index]) if f.is_dir()]
                self.all_speakers.extend(speaker_dirs)
                    
                print("search all wavs paths")
                start = time.time()

                for speaker in tqdm.tqdm(speaker_dirs):
                    speaker_dir =  p / speaker
                    wav_list=find_files(speaker_dir)
                    speaker_wav_dict[speaker] = []
                    for wav in wav_list:
                        wav_sample, _ = apply_effects_file(str(speaker_dir/wav), EFFECTS)
                        wav_sample = wav_sample.squeeze(0)
                        length = wav_sample.shape[0]

                        if length > self.vad_c['min_sec']:
                            utterance_id = "/".join(str(speaker_dir/wav).split("/")[-3:]).replace(".wav","").replace("/","-") 
                            self.dataset.append([str(speaker_dir/wav), utterance_id])
                            speaker_wav_dict[speaker].append("/".join(wav.split("/")[-2:]))
                end = time.time() 
                print(f"search all wavs paths costs {end-start} seconds")
                print(f"save wav paths to {cache_path}! so we can directly load all_path in next time!")
                pickle.dump(speaker_wav_dict, open(cache_path,"wb"))    

        self.speaker_num = len(self.all_speakers)
        self.necessary_dict = self.processing()
        self.label_mapping_spk_id = {}
        # speaker id  map to speaker num
        self.build_label_mapping()

        self.label=self.build_label(self.dataset)

    def processing(self):
        
        speaker_num = len(self.all_speakers)
        return {"spk_paths":self.all_speakers,"total_spk_num":speaker_num,"pair_table":None}

    
    # file_path/id0001/asfsafs/xxx.wav
    def build_label_mapping(self):
        spk_count  = 0
        for speaker_id in self.all_speakers:
            self.label_mapping_spk_id[speaker_id.split("/")[-1]] = spk_count
            spk_count +=1
        
    
    def build_label(self,train_path_list):
        y = []
        for path in train_path_list:
            id_string = path[0].split("/")[-3]
            y.append(self.label_mapping_spk_id[id_string])

        return y

    def __len__(self):
        return len(self.dataset)
    
    def __getitem__(self, idx):
        wav, _ = apply_effects_file(self.dataset[idx][0], EFFECTS)
        wav = wav.squeeze(0)
        length = wav.shape[0]
        
        if self.max_timestep !=None:
            if length > self.max_timestep:
                start = random.randint(0, int(length-self.max_timestep))
                wav = wav[start:start+self.max_timestep]
  
        return wav, self.dataset[idx][1], torch.tensor([self.label[idx]]).long()
        
    def collate_fn(self, samples):
        
        wavs, lengths, labels = [], [], []

        for wav,length,label in samples:
            wavs.append(wav)
            lengths.append(None)
            labels.append(label)
        return wavs, lengths, labels



class SpeakerVerifi_dev(Dataset):
    def __init__(self, vad_config, file_path, meta_data, max_timestep=None):
    
        self.root = file_path
        self.meta_data = meta_data
        self.necessary_dict = self.processing()
        self.vad_c = vad_config 
        self.max_timestep = max_timestep
        self.dataset = self.necessary_dict['pair_table'] 
        
    def processing(self):
        pair_table = []
        with open(self.meta_data, "r") as f:
            usage_list = f.readlines()
        for pair in usage_list:
            list_pair = pair.split()
            pair_1= os.path.join(self.root, list_pair[1])
            pair_2= os.path.join(self.root, list_pair[2])
            one_pair = [list_pair[0],pair_1,pair_2 ]
            pair_table.append(one_pair)
        return {"spk_paths":None,"total_spk_num":None,"pair_table":pair_table}

    def __len__(self):
        return len(self.necessary_dict['pair_table'])

    def __getitem__(self, idx):
        y_label, x1_path, x2_path = self.dataset[idx]

        wav1, _ = apply_effects_file(x1_path, EFFECTS)
        wav2, _ = apply_effects_file(x2_path, EFFECTS)

        wav1 = wav1.squeeze(0)
        wav2 = wav2.squeeze(0)

        length1 = wav1.shape[0]
        if self.max_timestep!=None:
            if length1 > self.max_timestep:
                length1 = self.max_timestep
                start = random.randint(0,length1 - self.max_timestep)
                wav1 = wav1[start:start+self.max_timestep]

        length2 = wav2.shape[0]

        if self.max_timestep!=None:
            if length2 > self.max_timestep:
                length2 = self.max_timestep
                start = random.randint(0,length2 - self.max_timestep)
                wav2 = wav1[start:start+self.max_timestep]


        return wav1, wav2, \
        torch.tensor(length1), torch.tensor(length2), \
        torch.tensor(int(y_label[0])),
    
    def collate_fn(self, data_sample):
        wavs1 = []
        wavs2 = []
        lengths1 = []
        lengths2 = []
        ylabels = []

        for samples in data_sample:
            wavs1.append(samples[0])
            wavs2.append(samples[1])
            lengths1.append(None)
            lengths2.append(None)
            ylabels.append(samples[4])

        all_wavs = []
        all_wavs.extend(wavs1)
        all_wavs.extend(wavs2)

        all_lengths = []
        all_lengths.extend(lengths1)
        all_lengths.extend(lengths2)

        return all_wavs, all_lengths, ylabels




class SpeakerVerifi_test(Dataset):
    def __init__(self, vad_config, file_path, meta_data):
        
        self.root = file_path
        self.meta_data = meta_data
        self.necessary_dict = self.processing()
        self.vad_c = vad_config 
        self.dataset = self.necessary_dict['pair_table'] 
        
    def processing(self):
        pair_table = []
        with open(self.meta_data, "r") as f:
            usage_list = f.readlines()
        for pair in usage_list:
            list_pair = pair.split()
            pair_1= os.path.join(self.root, list_pair[1])
            pair_2= os.path.join(self.root, list_pair[2])
            one_pair = [list_pair[0],pair_1,pair_2 ]
            pair_table.append(one_pair)
        return {"spk_paths":None,"total_spk_num":None,"pair_table":pair_table}

    def __len__(self):
        return len(self.necessary_dict['pair_table'])

    def __getitem__(self, idx):
        y_label, x1_path, x2_path = self.dataset[idx]

        wav1, _ = apply_effects_file(x1_path, EFFECTS)
        wav2, _ = apply_effects_file(x2_path, EFFECTS)

        wav1 = wav1.squeeze(0)
        wav2 = wav2.squeeze(0)

        length1 = wav1.shape[0]
        length2 = wav2.shape[0]

        return wav1, wav2, \
        torch.tensor(length1), torch.tensor(length2), \
        torch.tensor(int(y_label[0])),
    
    def collate_fn(self, data_sample):
        wavs1 = []
        wavs2 = []
        lengths1 = []
        lengths2 = []
        ylabels = []

        for samples in data_sample:
            wavs1.append(samples[0])
            wavs2.append(samples[1])
            lengths1.append(None)
            lengths2.append(None)
            ylabels.append(samples[4])

        all_wavs = []
        all_wavs.extend(wavs1)
        all_wavs.extend(wavs2)

        all_lengths = []
        all_lengths.extend(lengths1)
        all_lengths.extend(lengths2)

        return all_wavs, all_lengths, ylabels

