"""Dataset utils for different data settings for GLUE."""

import os
import copy
import logging
import torch
import numpy as np
import time
from filelock import FileLock
import json
import itertools
import random
import transformers
from src.processors import processors_mapping, num_labels_mapping, output_modes_mapping, compute_metrics_mapping, median_mapping
from transformers.data.processors.utils import InputFeatures
from transformers import DataProcessor, InputExample
import dataclasses
from dataclasses import dataclass
from typing import List, Optional, Union
from sentence_transformers import SentenceTransformer, util
from copy import deepcopy
import pandas as pd

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class OurInputFeatures(InputFeatures):
    """
    Inherit from Transformers' InputFeatuers.
    """

    input_ids: List[int]
    attention_mask: Optional[List[int]] = None
    token_type_ids: Optional[List[int]] = None
    label: Optional[Union[int, float]] = None
    mask_pos: Optional[List[int]] = None # Position of the mask token
    label_word_list: Optional[List[int]] = None # Label word mapping (dynamic)

    def to_json_string(self):
        """Serializes this instance to a JSON string."""
        return json.dumps(dataclasses.asdict(self)) + "\n"

def input_example_to_string(example, sep_token): 
    if example.text_b is None:
        print("I am at line 45 dataset.py")
        return example.text_a
    else:
        print("I am at line 48 dataset.py")
        # Warning: very simple hack here
        return example.text_a + ' ' + sep_token + ' ' + example.text_b

def input_example_to_tuple(example): 
    if example.text_b is None:
        print("I am at line 54 dataset.py")
        if pd.isna(example.text_a) or example.text_a is None:
            print("I am at line 56 dataset.py")
            return ['']
            logger.warn("Empty input")
        else:
            print("I am at line 60 dataset.py")
            return [example.text_a]
    else:
        print("I am at line 63 dataset.py")
        return [example.text_a, example.text_b]

def tokenize_multipart_input(
    input_text_list, 
    max_length, 
    tokenizer, 
    task_name=None, 
    prompt=False, 
    template=None,
    label_word_list=None, 
    first_sent_limit=None,
    other_sent_limit=None,
    gpt3=False,
    truncate_head=False,
    support_labels=None,
):
    def enc(text):
        print("I am at line 81 dataset.py")
        return tokenizer.encode(text, add_special_tokens=False)

    input_ids = []
    attention_mask = []
    token_type_ids = [] # Only for BERT
    mask_pos = None # Position of the mask token

    if prompt:
        print("I am at line 90 dataset.py")
        """
        Concatenate all sentences and prompts based on the provided template.
        Template example: '*cls*It was*mask*.*sent_0**<sep>*label_0:*sent_1**<sep>**label_1*:*sent_2**<sep>*'
        *xx* represent variables:
            *cls*: cls_token
            *mask*: mask_token
            *sep*: sep_token
            *sep+*: sep_token, also means +1 for segment id
            *sent_i*: sentence i (input_text_list[i])
            *sent-_i*: same as above, but delete the last token
            *sentl_i*: same as above, but use lower case for the first word
            *sentl-_i*: same as above, but use lower case for the first word and delete the last token
            *+sent_i*: same as above, but add a space before the sentence
            *+sentl_i*: same as above, but add a space before the sentence and use lower case for the first word
            *label_i*: label_word_list[i]
            *label_x*: label depends on the example id (support_labels needed). this is only used in GPT-3's in-context learning

        Use "_" to replace space.
        PAY ATTENTION TO SPACE!! DO NOT leave space before variables, for this will lead to extra space token.
        """
        assert template is not None

        special_token_mapping = {
            'cls': tokenizer.cls_token_id, 'mask': tokenizer.mask_token_id, 'sep': tokenizer.sep_token_id, 'sep+': tokenizer.sep_token_id, 
        }
        template_list = template.split('*') # Get variable list in the template
        segment_id = 0 # Current segment id. Segment id +1 if encountering sep+.

        for part_id, part in enumerate(template_list):
            new_tokens = []
            segment_plus_1_flag = False
            if part in special_token_mapping:
                print("I am at line 123 dataset.py")
                if part == 'cls' and 'T5' in type(tokenizer).__name__:
                    print("I am at line 125 dataset.py")
                    # T5 does not have cls token
                    continue
                new_tokens.append(special_token_mapping[part])
                if part == 'sep+':
                    print("I am at line 130 dataset.py")
                    segment_plus_1_flag = True
            elif part[:6] == 'label_':
                print("I am at line 133 dataset.py")
                # Note that label_word_list already has extra space, so do not add more space ahead of it.
                label_id = int(part.split('_')[1])
                label_word = label_word_list[label_id]
                new_tokens.append(label_word)
            elif part[:7] == 'labelx_':
                print("I am at line 139 dataset.py")
                instance_id = int(part.split('_')[1])
                label_id = support_labels[instance_id]
                label_word = label_word_list[label_id]
                new_tokens.append(label_word)
            elif part[:5] == 'sent_':
                print("I am at line 145 dataset.py")
                sent_id = int(part.split('_')[1])
                new_tokens += enc(input_text_list[sent_id])
            elif part[:6] == '+sent_':
                print("I am at line 148 dataset.py")
                # Add space
                sent_id = int(part.split('_')[1])
                new_tokens += enc(' ' + input_text_list[sent_id])
            elif part[:6] == 'sent-_':
                print("I am at line 154 dataset.py")
                # Delete the last token
                sent_id = int(part.split('_')[1])
                new_tokens += enc(input_text_list[sent_id][:-1])
            elif part[:6] == 'sentl_':
                print("I am at line 159 dataset.py")
                # Lower case the first token
                sent_id = int(part.split('_')[1])
                text = input_text_list[sent_id]
                text = text[:1].lower() + text[1:]
                new_tokens += enc(text)
            elif part[:7] == '+sentl_':
                print("I am at line 166 dataset.py")
                # Lower case the first token and add space 
                sent_id = int(part.split('_')[1])
                text = input_text_list[sent_id]
                text = text[:1].lower() + text[1:]
                new_tokens += enc(' ' + text)
            elif part[:7] == 'sentl-_':
                print("I am at line 173 dataset.py")
                # Lower case the first token and discard the last token
                sent_id = int(part.split('_')[1])
                text = input_text_list[sent_id]
                text = text[:1].lower() + text[1:]
                new_tokens += enc(text[:-1])
            elif part[:6] == 'sentu_':
                print("I am at line 180 dataset.py")
                # Upper case the first token
                sent_id = int(part.split('_')[1])
                text = input_text_list[sent_id]
                text = text[:1].upper() + text[1:]
                new_tokens += enc(text)
            elif part[:7] == '+sentu_':
                print("I am at line 187 dataset.py")
                # Upper case the first token and add space
                sent_id = int(part.split('_')[1])
                text = input_text_list[sent_id]
                text = text[:1].upper() + text[1:]
                new_tokens += enc(' ' + text)
            else:
                print("I am at line 194 dataset.py")
                # Just natural language prompt
                part = part.replace('_', ' ') 
                # handle special case when T5 tokenizer might add an extra space
                if len(part) == 1:
                    print("I am at line 199 dataset.py")
                    new_tokens.append(tokenizer._convert_token_to_id(part))
                else:
                    print("I am at line 202 dataset.py")
                    new_tokens += enc(part)

            if part[:4] == 'sent' or part[1:5] == 'sent':
                print("I am at line 206 dataset.py")
                # If this part is the sentence, limit the sentence length
                sent_id = int(part.split('_')[1])
                if sent_id == 0:
                    print("I am at line 210 dataset.py")
                    if first_sent_limit is not None:
                        print("I am at line 212 dataset.py")
                        new_tokens = new_tokens[:first_sent_limit]
                else:
                    print("I am at line 215 dataset.py")
                    if other_sent_limit is not None:
                        print("I am at line 217 dataset.py")
                        new_tokens = new_tokens[:other_sent_limit]

            input_ids += new_tokens
            attention_mask += [1 for i in range(len(new_tokens))]
            token_type_ids += [segment_id for i in range(len(new_tokens))]

            if segment_plus_1_flag:
                print("I am at line 225 dataset.py")
                segment_id += 1
    else:
        print("I am at line 228 dataset.py")
        input_ids = [tokenizer.cls_token_id]
        attention_mask = [1]
        token_type_ids = [0]

        for sent_id, input_text in enumerate(input_text_list):
            if input_text is None:
                print("I am at line 235 dataset.py")
                # Do not have text_b
                continue
            if pd.isna(input_text) or input_text is None:
                print("I am at line 239 dataset.py")
                # Empty input
                input_text = ''
            input_tokens = enc(input_text) + [tokenizer.sep_token_id]
            input_ids += input_tokens
            attention_mask += [1 for i in range(len(input_tokens))]
            token_type_ids += [sent_id for i in range(len(input_tokens))]

        if 'T5' in type(tokenizer).__name__: # T5 does not have CLS token
            print("I am at line 248 dataset.py")
            input_ids = input_ids[1:]
            attention_mask = attention_mask[1:]
            token_type_ids = token_type_ids[1:]

    # Padding
    if first_sent_limit is not None and len(input_ids) > max_length:
        print("I am at line 255 dataset.py")
        # If using sentence limit, the total length still exceeds the maximum limit, report a warning
        logger.warn("Input exceeds max_length limit ({}): {}".format(len(input_ids), tokenizer.decode(input_ids)))

    while len(input_ids) < max_length:
        input_ids.append(tokenizer.pad_token_id)
        attention_mask.append(0)
        token_type_ids.append(0)
        

    # Truncate
    if len(input_ids) > max_length:
        print("I am at line 268 dataset.py")
        if truncate_head:
            print("I am at line 270 dataset.py")
            input_ids = input_ids[-max_length:]
            attention_mask = attention_mask[-max_length:]
            token_type_ids = token_type_ids[-max_length:]
        else:
            print("I am at line 275 dataset.py")
            # Default is to truncate the tail
            input_ids = input_ids[:max_length]
            attention_mask = attention_mask[:max_length]
            token_type_ids = token_type_ids[:max_length]
            

    # Find mask token
    if prompt:
        print("I am at line 284 dataset.py")
        # print(tokenizer.decode(input_ids))
        mask_pos = [input_ids.index(tokenizer.mask_token_id)]
        # Make sure that the masked position is inside the max_length
        assert mask_pos[0] < max_length

    result = {'input_ids': input_ids, 'attention_mask': attention_mask}
    if 'BERT' in type(tokenizer).__name__:
        print("I am at line 292 dataset.py")
        # Only provide token type ids for BERT
        result['token_type_ids'] = token_type_ids

    if prompt:
        print("I am at line 297 dataset.py")
        result['mask_pos'] = mask_pos

    return result



class FewShotDataset(torch.utils.data.Dataset):
    """Few-shot dataset."""

    def __init__(self, args, tokenizer, cache_dir=None, mode="train", use_demo=False):
        self.args = args
        self.task_name = args.task_name
        self.processor = processors_mapping[args.task_name]
        self.tokenizer = tokenizer
        self.mode = mode

        # If not using demonstrations, use use_demo=True
        self.use_demo = use_demo
        if self.use_demo:
            print("I am at line 317 dataset.py")
            logger.info("Use demonstrations")
        assert mode in ["train", "dev", "test"]

        # Get label list and (for prompt) label word list
        self.label_list = self.processor.get_labels()
        self.num_labels = len(self.label_list)
        if args.prompt:
            print("I am at line 325 dataset.py")
            assert args.mapping is not None
            self.label_to_word = eval(args.mapping)

            for key in self.label_to_word:
                # For RoBERTa/BART/T5, tokenization also considers space, so we use space+word as label words.
                if self.label_to_word[key][0] not in ['<', '[', '.', ',']:
                    print("I am at line 332 dataset.py")
                    # Make sure space+word is in the vocabulary
                    assert len(tokenizer.tokenize(' ' + self.label_to_word[key])) == 1
                    self.label_to_word[key] = tokenizer._convert_token_to_id(tokenizer.tokenize(' ' + self.label_to_word[key])[0])
                else:
                    print("I am at line 337 dataset.py")
                    self.label_to_word[key] = tokenizer._convert_token_to_id(self.label_to_word[key])
                logger.info("Label {} to word {} ({})".format(key, tokenizer._convert_id_to_token(self.label_to_word[key]), self.label_to_word[key]))
            
            if len(self.label_list) > 1:
                print("I am at line 342 dataset.py")
                self.label_word_list = [self.label_to_word[label] for label in self.label_list]
            else:
                print("I am at line 345 dataset.py")
                # Regression task
                # '0' represents low polarity and '1' represents high polarity.
                self.label_word_list = [self.label_to_word[label] for label in ['0', '1']]
        else:
            print("I am at line 350 dataset.py")
            self.label_to_word = None
            self.label_word_list = None

        # Multiple sampling: when using demonstrations, we sample different combinations of demonstrations during 
        # inference and aggregate the results by averaging the logits. The number of different samples is num_sample.
        if (mode == "train") or not self.use_demo:
            print("I am at line 357 dataset.py")
            # We do not do multiple sampling when not using demonstrations or when it's the training mode 
            self.num_sample = 1    
        else:
            print("I am at line 361 dataset.py")
            self.num_sample = args.num_sample

        # If we use multiple templates, we also need to do multiple sampling during inference.
        if args.prompt and args.template_list is not None:
            print("I am at line 366 dataset.py")
            logger.info("There are %d templates. Multiply num_sample by %d" % (len(args.template_list), len(args.template_list)))
            self.num_sample *= len(args.template_list)
                
        logger.info("Total num_sample for mode %s: %d" % (mode, self.num_sample))

        # Load cache
        # Cache name distinguishes mode, task name, tokenizer, and length. So if you change anything beyond these elements, make sure to clear your cache.
        cached_features_file = os.path.join(
            cache_dir if cache_dir is not None else args.data_dir,
            "cached_{}_{}_{}_{}".format(
                mode,
                tokenizer.__class__.__name__,
                str(args.max_seq_length),
                args.task_name,
            ),
        )

        logger.info(f"Creating/loading examples from dataset file at {args.data_dir}")

        lock_path = cached_features_file + ".lock"
        with FileLock(lock_path):

            if os.path.exists(cached_features_file) and not args.overwrite_cache:
                print("I am at line 390 dataset.py")
                start = time.time()
                self.support_examples, self.query_examples = torch.load(cached_features_file)
                logger.info(
                    f"Loading features from cached file {cached_features_file} [took %.3f s]", time.time() - start
                )
            else:
                print("I am at line 397 dataset.py")
                logger.info(f"Creating features from dataset file at {args.data_dir}")

                # The support examples are sourced from the training set.
                self.support_examples = self.processor.get_train_examples(args.data_dir)

                if mode == "dev":
                    print("I am at line 404 dataset.py")
                    self.query_examples = self.processor.get_dev_examples(args.data_dir)
                elif mode == "test":
                    print("I am at line 407 dataset.py")
                    self.query_examples = self.processor.get_test_examples(args.data_dir)
                else:
                    print("I am at line 410 dataset.py")
                    self.query_examples = self.support_examples

                start = time.time()
                torch.save([self.support_examples, self.query_examples], cached_features_file)
                # ^ This seems to take a lot of time so I want to investigate why and how we can improve.
                logger.info(
                    "Saving features into cached file %s [took %.3f s]", cached_features_file, time.time() - start
                )

        # For filtering in using demonstrations, load pre-calculated embeddings
        if self.use_demo and args.demo_filter:
            print("I am at line 422 dataset.py")
            split_name = ''
            if mode == 'train':
                print("I am at line 425 dataset.py")
                split_name = 'train'
            elif mode == 'dev':
                print("I am at line 428 dataset.py")
                if args.task_name == 'mnli':
                    split_name = 'dev_matched'
                elif args.task_name == 'mnli-mm':
                    split_name = 'dev_mismatched'
                else:
                    split_name = 'dev'
            elif mode == 'test':
                print("I am at line 436 dataset.py")
                if args.task_name == 'mnli':
                    split_name = 'test_matched'
                elif args.task_name == 'mnli-mm':
                    split_name = 'test_mismatched'
                else:
                    split_name = 'test'
            else:
                raise NotImplementedError

            self.support_emb = np.load(os.path.join(args.data_dir, "train_{}.npy".format(args.demo_filter_model)))
            self.query_emb = np.load(os.path.join(args.data_dir, "{}_{}.npy".format(split_name, args.demo_filter_model)))
            logger.info("Load embeddings (for demonstration filtering) from {}".format(os.path.join(args.data_dir, "{}_{}.npy".format(split_name, args.demo_filter_model))))

            assert len(self.support_emb) == len(self.support_examples)
            assert len(self.query_emb) == len(self.query_examples)
 
        # Size is expanded by num_sample
        self.size = len(self.query_examples) * self.num_sample
        
        # Prepare examples (especially for using demonstrations)
        support_indices = list(range(len(self.support_examples)))
        self.example_idx = []
        for sample_idx in range(self.num_sample):
            for query_idx in range(len(self.query_examples)):
                # If training, exclude the current example. Else keep all.
                if self.use_demo and args.demo_filter:
                    print("I am at line 463 dataset.py")
                    # Demonstration filtering
                    candidate = [support_idx for support_idx in support_indices
                                   if support_idx != query_idx or mode != "train"]
                    sim_score = []
                    for support_idx in candidate:
                        sim_score.append((support_idx, util.pytorch_cos_sim(self.support_emb[support_idx], self.query_emb[query_idx])))
                    sim_score.sort(key=lambda x: x[1], reverse=True)
                    if self.num_labels == 1:
                        print("I am at line 472 dataset.py")
                        # Regression task
                        limit_each_label = int(len(sim_score) // 2 * args.demo_filter_rate)
                        count_each_label = {'0': 0, '1': 0}
                        context_indices = []

                        if args.debug_mode:
                            print("I am at line 479 dataset.py")
                            print("Query %s: %s" % (self.query_examples[query_idx].label, self.query_examples[query_idx].text_a)) # debug
                        for support_idx, score in sim_score:
                            if count_each_label['0' if float(self.support_examples[support_idx].label) <= median_mapping[args.task_name] else '1'] < limit_each_label:
                                print("I am at line 483 dataset.py")
                                count_each_label['0' if float(self.support_examples[support_idx].label) <= median_mapping[args.task_name] else '1'] += 1
                                context_indices.append(support_idx)
                                if args.debug_mode:
                                    print("I am at line 487 dataset.py")
                                    print("    %.4f %s | %s" % (score, self.support_examples[support_idx].label, self.support_examples[support_idx].text_a)) # debug
                    else:
                        print("I am at line 490 dataset.py")
                        limit_each_label = int(len(sim_score) // self.num_labels * args.demo_filter_rate)
                        count_each_label = {label: 0 for label in self.label_list}
                        context_indices = []

                        if args.debug_mode:
                            print("I am at line 496 dataset.py")
                            print("Query %s: %s" % (self.query_examples[query_idx].label, self.query_examples[query_idx].text_a)) # debug
                        for support_idx, score in sim_score:
                            if count_each_label[self.support_examples[support_idx].label] < limit_each_label:
                                print("I am at line 500 dataset.py")
                                count_each_label[self.support_examples[support_idx].label] += 1
                                context_indices.append(support_idx)
                                if args.debug_mode:
                                    print("I am at line 504 dataset.py")
                                    print("    %.4f %s | %s" % (score, self.support_examples[support_idx].label, self.support_examples[support_idx].text_a)) # debug
                else:
                    print("I am at line 507 dataset.py")
                    # Using demonstrations without filtering
                    context_indices = [support_idx for support_idx in support_indices
                               if support_idx != query_idx or mode != "train"]

                # We'll subsample context_indices further later.
                self.example_idx.append((query_idx, context_indices, sample_idx))

        # If it is not training, we pre-process the data; otherwise, we process the data online.
        if mode != "train":
            print("I am at line 517 dataset.py")
            self.features = []
            _ = 0
            for query_idx, context_indices, bootstrap_idx in self.example_idx:
                # The input (query) example
                example = self.query_examples[query_idx]
                # The demonstrations
                supports = self.select_context([self.support_examples[i] for i in context_indices])

                if args.template_list is not None:
                    print("I am at line 527 dataset.py")
                    template = args.template_list[sample_idx % len(args.template_list)] # Use template in order
                else:
                    print("I am at line 530 dataset.py")
                    template = args.template
                    

                self.features.append(self.convert_fn(
                    example=example,
                    supports=supports,
                    use_demo=self.use_demo,
                    label_list=self.label_list,
                    prompt=args.prompt,
                    template=template,
                    label_word_list=self.label_word_list,
                    verbose= True if _ == 0 else False,
                ))

                _ += 1
        else:
            print("I am at line 547 dataset.py")
            self.features = None

    def select_context(self, context_examples):
        """
        Select demonstrations from provided examples.
        """
        max_demo_per_label = 1
        counts = {k: 0 for k in self.label_list}
        if len(self.label_list) == 1:
            print("I am at line 557 dataset.py")
            # Regression
            counts = {'0': 0, '1': 0}
        selection = []

        if self.args.gpt3_in_context_head or self.args.gpt3_in_context_tail:
            print("I am at line 563 dataset.py")
            # For GPT-3's in-context learning, we sample gpt3_in_context_num demonstrations randomly. 
            order = np.random.permutation(len(context_examples))
            for i in range(min(self.args.gpt3_in_context_num, len(order))):
                selection.append(context_examples[order[i]])
        else:
            print("I am at line 569 dataset.py")
            # Our sampling strategy
            order = np.random.permutation(len(context_examples))

            for i in order:
                label = context_examples[i].label
                if len(self.label_list) == 1:
                    print("I am at line 576 dataset.py")
                    # Regression
                    label = '0' if float(label) <= median_mapping[self.args.task_name] else '1'
                if counts[label] < max_demo_per_label:
                    print("I am at line 580 dataset.py")
                    selection.append(context_examples[i])
                    counts[label] += 1
                if sum(counts.values()) == len(counts) * max_demo_per_label:
                    print("I am at line 584 dataset.py")
                    break
        
            assert len(selection) > 0
        
        return selection

    def __len__(self):
        return self.size

    def __getitem__(self, i):
        if self.features is None:
            print("I am at line 596 dataset.py")
            query_idx, context_indices, bootstrap_idx = self.example_idx[i]
            # The input (query) example
            example = self.query_examples[query_idx]
            # The demonstrations
            supports = self.select_context([self.support_examples[i] for i in context_indices])

            if self.args.template_list is not None:
                print("I am at line 604 dataset.py")
                template = self.args.template_list[sample_idx % len(self.args.template_list)]
            else:
                print("I am at line 607 dataset.py")
                template = self.args.template

            features = self.convert_fn(
                example=example,
                supports=supports,
                use_demo=self.use_demo,
                label_list=self.label_list,
                prompt=self.args.prompt,
                template=template,
                label_word_list=self.label_word_list,
                verbose=False,
            )
        else:
            print("I am at line 621 dataset.py")
            features = self.features[i]
            
        return features

    def get_labels(self):
        return self.label_list


    def convert_fn(
        self,
        example,
        supports,
        use_demo=False,
        label_list=None,
        prompt=False,
        template=None,
        label_word_list=None,
        verbose=False
    ):
        """
        Returns a list of processed "InputFeatures".
        """
        max_length = self.args.max_seq_length    

        # Prepare labels
        label_map = {label: i for i, label in enumerate(label_list)} # Mapping the label names to label ids
        if len(label_list) == 1:
            print("I am at line 649 dataset.py")
            # Regression
            label_map = {'0': 0, '1': 1}

        # Get example's label id (for training/inference)
        if example.label is None:
            print("I am at line 655 dataset.py")
            example_label = None
        elif len(label_list) == 1:
            print("I am at line 658 dataset.py")
            # Regerssion
            example_label = float(example.label)
        else:
            print("I am at line 662 dataset.py")
            example_label = label_map[example.label]

        # Prepare other features
        if not use_demo:
            print("I am at line 667 dataset.py")
            # No using demonstrations
            inputs = tokenize_multipart_input(
                input_text_list=input_example_to_tuple(example),
                max_length=max_length,
                tokenizer=self.tokenizer,
                task_name=self.args.task_name,
                prompt=prompt,
                template=template,
                label_word_list=label_word_list,
                first_sent_limit=self.args.first_sent_limit,
                other_sent_limit=self.args.other_sent_limit,
                truncate_head=self.args.truncate_head,
            )
            features = OurInputFeatures(**inputs, label=example_label)

        else:
            print("I am at line 684 dataset.py")
            # Using demonstrations

            # Max length
            if self.args.double_demo:
                print("I am at line 689 dataset.py")
                # When using demonstrations, double the maximum length
                # Note that in this case, args.max_seq_length is the maximum length for a single sentence
                max_length = max_length * 2
            if self.args.gpt3_in_context_head or self.args.gpt3_in_context_tail:
                print("I am at line 694 dataset.py")
                # When using GPT-3's in-context learning, take the maximum tokenization length of the model (512)
                max_length = 512

            # All input sentences, including the query and the demonstrations, are put into augmented_examples, 
            # and are numbered based on the order (starting from 0). For single sentence tasks, the input (query)
            # is the sentence 0; for sentence-pair tasks, the input (query) is the sentence 0 and 1. Note that for GPT-3's 
            # in-context learning, the input (query) might be at the end instead of the beginning (gpt3_in_context_head)
            augmented_example = []
            query_text = input_example_to_tuple(example) # Input sentence list for query
            support_by_label = [[] for i in range(len(label_map))]

            if self.args.gpt3_in_context_head or self.args.gpt3_in_context_tail:
                print("I am at line 707 dataset.py")
                support_labels = []
                augmented_example = query_text
                for support_example in supports:
                    augmented_example += input_example_to_tuple(support_example)
                    current_label = support_example.label
                    if len(label_list) == 1:
                        print("I am at line 714 dataset.py")
                        current_label = '0' if float(current_label) <= median_mapping[self.args.task_name] else '1' # Regression
                    support_labels.append(label_map[current_label])
            else:
                print("I am at line 718 dataset.py")
                # Group support examples by label
                for label_name, label_id in label_map.items():
                    if len(label_list) == 1:
                        print("I am at line 718 dataset.py")
                        # Regression
                        for support_example in filter(lambda s: ('0' if float(s.label) <= median_mapping[self.args.task_name] else '1') == label_name, supports):
                            support_by_label[label_id] += input_example_to_tuple(support_example)
                    else:
                        print("I am at line 727 dataset.py")
                        for support_example in filter(lambda s: s.label == label_name, supports):
                            support_by_label[label_id] += input_example_to_tuple(support_example)

                augmented_example = query_text
                for label_id in range(len(label_map)):
                    augmented_example += support_by_label[label_id]
                    
            # Tokenization (based on the template)
            inputs = tokenize_multipart_input(
                input_text_list=augmented_example,
                max_length=max_length,
                tokenizer=self.tokenizer,
                task_name=self.args.task_name,
                prompt=prompt,
                template=template,
                label_word_list=label_word_list,
                first_sent_limit=self.args.first_sent_limit,
                other_sent_limit=self.args.other_sent_limit,
                truncate_head=self.args.truncate_head,
                gpt3=self.args.gpt3_in_context_head or self.args.gpt3_in_context_tail,
                support_labels=None if not (self.args.gpt3_in_context_head or self.args.gpt3_in_context_tail) else support_labels
            )
            features = OurInputFeatures(**inputs, label=example_label)

        if verbose:
            logger.info("*** Example ***")
            logger.info("guid: %s" % (example.guid))
            logger.info("features: %s" % features)
            logger.info("text: %s" % self.tokenizer.decode(features.input_ids))

        return features



